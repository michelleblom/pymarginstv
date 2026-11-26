#!/bin/bash
# Runs the C++ program from the combine-dive branch on the 2025 Senate
# contests with -dive (before the search, cheap alternative outcomes near
# the reported last seats are tried and improved step by step, and the best
# becomes the starting upper bound), one contest per array task, with every
# bound improvement (-sumq -multielim -sumnq -elimnq) and -nominlps,
# 10 hour limit.
# Usage: sbatch --cpus-per-task=32 --export=ALL,PC=32 run_senate_2025_dive.slurm
#   PC defaults to 64. Keep --cpus-per-task about equal to PC.
#   Tasks 0-5 are the 6-seat states; 6 and 7 are the 2-seat territories,
#   run with e.g. --array=6,7 (numbers match the lists below).

#SBATCH --job-name=senate25dv
#SBATCH --account=sz64
#SBATCH --array=0-5

# One program per task, one thread per frontier node expanded each step
#SBATCH --ntasks=1
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=64

# Memory grows with the CPU count: 64 x 2000 MB = 128 GB
#SBATCH --mem-per-cpu=2000

# 10 hour search limit plus time to start up and write the summary
#SBATCH --time=0-11:00:00

#SBATCH --mail-user=michelle.blom@democracydevelopers.org.au
#SBATCH --mail-type=END
#SBATCH --mail-type=FAIL

# %A = array job id, %a = task number
#SBATCH --output=senate25dv-%A_%a.out
#SBATCH --error=senate25dv-%A_%a.err


BIN=$HOME/sz64/combine-dive/cpp/build/marginstv
DATA=$HOME/sz64_scratch/data
PC=${PC:-64}

FILES=(FedAus25/FederalSenate2025NSW.json FedAus25/FederalSenate2025QLD.json
       FedAus25/FederalSenate2025SA.json FedAus25/FederalSenate2025TAS.json
       FedAus25/FederalSenate2025VIC.json FedAus25/FederalSenate2025WA.json
       FedAus25/2025ACT.json FedAus25/2025NT.json)
NAMES=('NSW 25' 'QLD 25' 'SA 25' 'TAS 25' 'VIC 25' 'WA 25' 'ACT 25' 'NT 25')
SEATS=(6 6 6 6 6 6 2 2)

i=$SLURM_ARRAY_TASK_ID
FILE=${FILES[$i]}

"$BIN" -d "$DATA/$FILE" -s "${SEATS[$i]}" -displayname "${NAMES[$i]}" \
    -pc "$PC" -g 0.01 -agap 0 -m -limit 36000 \
    -lse -eqlbc -dlbc -useqprefix -prec_et \
    -sumq -multielim -sumnq -elimnq -nominlps \
    -dive \
    -threads "$SLURM_CPUS_PER_TASK" \
    -orders "orders_${FILE//\//}_M3_pc${PC}_dive.txt" \
    -log "log_${FILE//\//}_M3_pc${PC}_dive_cpp.log" \
    | tail -n 1 > "summary_2025_dive_pc${PC}_${i}.csv"
