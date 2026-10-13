# marginstv (C++) — architecture proposal

Status: draft for approval. Nothing is implemented yet.

## Goal

A C++20 program, `marginstv`, that takes the same command line as
`pymarginstv.py`, runs the same branch-and-bound search, and writes the same
log, line for line. The only lines allowed to differ are the ones that print
wall-clock times (`Time elapsed`, `Time to finish`, `Time start`) and the
final stdout CSV's two time columns. It should be faster per node and use far
less memory, so a fixed time budget gets further through the search.

## What must match exactly, and what that forces

The log prints raw floating-point values (simulation tallies, transfer values)
and integer bounds produced by `ceil` of floating-point sums. Several design
rules follow from that.

1. **Same arithmetic, same order.** Every sum over ballots is taken in ballot
   order, exactly as Python does. No `-ffast-math`, and `-ffp-contract=off` so
   the compiler cannot fuse a multiply and add into one instruction (Apple
   clang does this by default on ARM, and it changes the last bit).
2. **Python number printing.** A small formatting module reproduces Python's
   `str()` for floats (shortest round-trip digits, `1234.0`, `inf`,
   `1e+16`) and keeps track of whether a value is an int or a float, because
   Python prints `5` and `5.0` differently. In practice the search's bounds are
   all ints; the election simulation mixes both.
3. **Python container printing.** Lists print as `[1, 2]`, quota maps as
   `{3: (-1, 0), 5: (7, 7)}` in insertion order.
4. **Python set iteration order.** In the default (non-quota-prefix) mode,
   `get_order_q` builds the quota map by iterating a Python `set` of winners,
   and that order shows up in the log. Candidate numbers above 7 can come out
   unsorted. A small module emulates CPython 3.9's set slot layout so the order
   matches. It is checked against real Python in the unit tests.
5. **The search shape cannot depend on thread count.** `-pc` keeps its Python
   meaning: how many frontier nodes are popped per step. A new `-threads`
   option sets how many cores are used (default: all). Results are gathered
   into slots indexed by (popped node, child) and logged by one thread, in
   Python's order, after the whole batch finishes. The running upper bound is
   frozen for the duration of a batch, as it is in Python. So `-pc 15` gives
   the same log on 1 thread or 64.

## Reference logs (`15PC_logs`)

The current Python reproduces these logs exactly when it is run with the same
flags and `-pc 15`. The search order depends on `-pc`, so comparisons must
use `-pc 15`. The set mixes two version-to-flag mappings:

- Scotland, Ireland, Minneapolis (versions 3–9): the current
  `run_experiments.py` mapping, `-limit 10000`.
- FedAus (versions 9, 10, 11): the earlier mapping, `-limit 36000`.
  9 = `-lse -eqlbc -dlbc -useqprefix -nominlps -prec_et`,
  10 = `-lse -eqlbc -dlbc -prec_et -nominlps`, 11 = `-lse -eqlbc -dlbc`.

185 runs converged, 35 stopped on the time limit, and 2 were killed mid-run
(WA 2019 version 10, ACT 2022 version 11). For runs that did not converge,
the C++ log is compared line by line up to where the Python log ends. A
faster program will carry on past that point.

## Source layout

```
cpp/
  CMakeLists.txt  .clang-format  .clang-tidy
  include/marginstv/   one .hpp per module below
  src/                 matching .cpp files
  app/main.cpp         command line, top-level flow (pymarginstv.py)
  tests/               see the separate test plan (step 2)
```

| Module | Replaces (Python) | Contents |
|---|---|---|
| `options` | argparse in `pymarginstv.py` | Every existing flag, same names and defaults, plus `-threads`. |
| `pyformat` | `print`/`format` | Float/int printing, list and dict printing, the `PyNum` int-or-float value. |
| `pyset_order` | CPython `set` | Iteration order of a set of small ints built by a given sequence of adds/copies. |
| `ballots` | `utils.py` readers, `Ballot`, `Candidate`, `BallotMetadata` | Read `.blt`, `.txt`, `.json` (simdjson). Ballots stored once, read-only, shared by all threads. |
| `simulate` | `simulate_stv`, `compute_weub`, `compute_simple_ub` | The reported count and its log lines. |
| `prefix` | `compute_last_round`, `get_order_q`, `merge_outcome`, `derive_*`, `outcome_signature` | Outcome-prefix helpers. Signature is the same canonical byte encoding hashed with BLAKE2b-128. |
| `ballot_pass` | the loops over `ballots` | The shared engine every ballot walk runs through (see parallelism, level 3). |
| `eqlb` | `compute_elim_quota_lb_*`, `backcompute_nq_bound`, `calc_tallies*`, `compute_round_tallies*` | Elimination / quota / no-quota bounds, both prefix modes. |
| `displb` | `compute_disp_lb_*`, `update_disp_cache*`, `build_disp_arrays` | Displacement bound, both prefix modes. |
| `distance` | `stvdistance.py`, `stvdistance-qprefix.py`, equivalence classes, `reduce_ballots` | MINLP models through SCIP's C API, the two early-stop event handlers, and the `.solves.csv` sidecar. |
| `frontier` | `TreeNode`, `Frontier` | Ordered frontier, subsumption table, pruning, printing. |
| `search` | `treestv`, `eval_child*`, `generate_children`, `expand_node` | The branch-and-bound loop and batch scheduling. |

## Parallelism

Threads, not processes, using oneTBB's work-stealing task scheduler. Nested
tasks are its normal case: an idle core steals whatever is waiting, at any
level, so a batch with one slow node does not leave cores idle.

**Level 1 — popped nodes.** The `-pc` nodes popped in one step are expanded
concurrently (what Python does with its process pool).

**Level 2 — inside one node.** The work a node's children share (rebuilding
the displacement summaries, and the precomputed round tallies under
`-prec_et`) runs as two concurrent tasks. Then all the node's children are
evaluated concurrently. Python can do only one of level 1 or level 2 at a
time (`-evalpara`); here both run together. `-evalpara` is accepted and
ignored.

**Level 3 — inside one ballot walk.** This is where the time goes on large
contests: each bound walks every ballot type. A plain parallel sum would add
in a different order and change the last bits, so each walk is split in two:

- *Phase A, parallel over ballots:* work out each ballot's value and where it
  sits after the prefix (the expensive `calc_tallies` part). Each ballot is
  independent, so results are bit-identical to Python's.
- *Phase B, parallel over output entries:* each task owns a set of output
  entries (for example, some rows of the N×N `above` table) and adds the
  phase A results into them in ballot order. Every entry therefore sees
  exactly Python's sequence of additions.

Ballots are processed in fixed-size blocks (about 64k) so phase A scratch
space stays small and is reused per thread. Small contests skip the split and
run the walk straight through.

**Level 4 — MINLP solves.** Each solve is a task like any other, so a 100 s
solve occupies one core while the rest carry on. SCIP runs single-threaded
per solve. Thread safety of the SCIP build (and its bundled Ipopt/MUMPS) is
the main technical risk; it is checked first (see below), and if it fails,
solves move to a small pool of helper processes behind the same interface.

## Memory

- One copy of the ballots for the whole run, laid out flat: all preference
  lists in one byte array (two bytes per preference above 255 candidates),
  plus offsets and vote counts. Python under `-pc 15` holds roughly 15 copies.
- Frontier nodes store the prefix packed as bytes, the quota map as a small
  array of 16-bit triples, the 16-byte signature, and the bound contexts.
  The rounds-gone list, its set and position map are rebuilt on expansion, as
  Python already does.
- The displacement tables (`above`, `reassign`: N×N each) are immutable and
  reference-counted. Children that carry a parent's tables forward share one
  copy instead of each holding their own, which Python cannot do because
  results come back from worker processes as separate copies.
- Per-round no-quota masks are a bitset of N bits per round, as in Python.
- Frontier: an ordered tree keyed by (distance, insertion number), which gives
  Python's tie order. Subsumption table: a flat hash map from 16-byte
  signature to a small sorted vector of distances.
- `cap_worker_count` is unnecessary (threads share memory) and is not ported;
  `-nopccap` is accepted and ignored. Python's warning line therefore never
  appears.

## Dependencies and build

- CMake, C++20, Apple clang (already installed). Flags: `-O3
  -ffp-contract=off`, no fast-math. `clang-format` and `clang-tidy`
  configuration included.
- oneTBB (Homebrew `tbb`), simdjson (already installed), SCIP.
- BLAKE2b: a small bundled implementation (about 150 lines, public domain
  reference code), so no extra library.
- Unit tests: Catch2 (fetched by CMake).

**SCIP version matters for log fidelity.** pyscipopt here runs SCIP 10.0.2
with its own bundled Ipopt. Homebrew offers 10.1.0. A different SCIP version
can take a different path through a solve and, when a solve hits its time or
gap limit, return a different bound, which then changes the log. Two options:

- (a) Link the exact `libscip.10.0.2` binary that pyscipopt uses, compiling
  against the matching 10.0.2 headers. Best fidelity.
- (b) Use Homebrew's 10.1.0. Simpler; expect some MINLP-version differences.

Even with (a), a solve that stops on its time limit (`-t`, `-thard`) depends
on machine speed, so logs from MINLP-using runs can only be expected to match
when no solve hits its time limit. Runs with `-nominlps` have no such issue.

## C++ style (per CLAUDE.md)

RAII throughout; no raw owning pointers; `std::unique_ptr`/`std::shared_ptr`
for ownership (the shared, immutable tables use `shared_ptr<const T>`); Rule
of Zero by default; single-argument constructors `explicit`; `const` member
functions where possible; move operations `noexcept`; West const; AAA where
it reads better. SCIP handles are wrapped in RAII owners so every solve frees
its problem on every exit path.

## Implementation order (step 3)

1. Build skeleton, readers, simulation and formatting: the log up to the
   `WEUB` line must match for every reference instance.
2. SCIP thread-safety check: concurrent solves of the same model must give
   the same results as sequential ones.
3. Bounds (`eqlb`, `displb`), sequential first, checked against Python on
   every child of small runs.
4. Frontier and search loop, sequential: full logs match for `-nominlps`
   runs.
5. MINLP models: full logs match for MINLP runs.
6. Turn on parallel levels 1–4 one at a time; logs must stay identical at
   every thread count.
7. Measure speed and memory against Python on the large senate contests.
