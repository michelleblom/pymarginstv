# marginstv (C++)

C++20 port of `pymarginstv.py`. Same command line, same search, same log,
with the work spread over all cores. See `ARCHITECTURE.md` for the design
and `tests/TEST_PLAN.md` for how it is checked against the Python.

## Build

The program links the SCIP library that pyscipopt uses on the same machine,
so MINLP solves behave as in the Python program there. CMake asks pyscipopt
which SCIP version it runs and downloads the matching SCIP headers from
GitHub (SCIP itself is not built). It needs:

- a C++20 compiler: GCC 11 or newer, or Apple clang 15 or newer
- CMake 3.22 or newer, oneTBB, simdjson, zlib, git
- `python3` with pyscipopt installed

macOS (Homebrew):

```
brew install cmake tbb simdjson
```

Ubuntu 22.04 or 24.04:

```
sudo apt install build-essential cmake git zlib1g-dev libtbb-dev libsimdjson-dev
```

Ubuntu 20.04: its CMake and GCC are too old, and its TBB and simdjson
packages too; the build downloads those two itself when it finds no
suitable copy. Install a newer CMake and GCC:

```
python3 -m pip install --user cmake          # puts cmake in ~/.local/bin
sudo add-apt-repository ppa:ubuntu-toolchain-r/test
sudo apt install g++-11 zlib1g-dev git
export CC=gcc-11 CXX=g++-11                   # before the first cmake run
```

Then, in this folder:

```
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build -j
```

Options: `-DMARGINSTV_FETCH_DEPS=ON` always downloads oneTBB and simdjson;
`-DMARGINSTV_TESTS=OFF` skips the tests (and the Catch2
download); `-DSCIP_SOURCE_DIR=...` uses a local SCIP source tree of the
right version instead of downloading one; `-DSCIP_LIBRARY=...` links a SCIP
library other than pyscipopt's; `-DMARGINSTV_DATA_DIR=...` tells the tests
where the election data is (default `../../stv-rla/data`; the e2e scripts
take `--data-dir`). The program stops with an error if the
linked library is not the version the headers came from.

## Run

Flags are those of `pymarginstv.py`, plus `-threads N` (default: all cores).
`-pc` keeps its Python meaning, the number of frontier nodes expanded per
step, so a run gives the same log as the Python with the same `-pc`,
whatever `-threads` is.

```
build/marginstv -d ../../stv-rla/data/Scotland/2007/GCC_07_Canal_ballots.txt -s 4 \
    -pc 15 -g 0.01 -agap 0 -m -ub 126 -lse -eqlb -dlb -log canal.log
```

## Test

```
python3 tests/golden/dump_golden.py          # golden data from the Python (once per machine)
python3 tests/e2e/make_extra_refs.py         # extra Python references (once)
build/marginstv_tests                        # unit, replay and SCIP model tests
python3 tests/e2e/run_e2e.py --tier quick    # logs against 15PC_logs
```

## Differences from the Python

- Threads, not processes: memory is shared, so `-nopccap` has no effect
  and the Python's warning about reducing `-pc` is never printed.
- The time lines in the log and the two time columns of the summary line
  report this program's own timings.
