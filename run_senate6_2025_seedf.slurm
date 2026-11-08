#!/bin/bash
# Runs the C++ program on the 2025 6-seat Senate contests with -weakseed at
# three budget fractions, -seedf 0.25, 0.5 and 0.75: one contest and fraction
# per array task, with every bound improvement (-sumq -multielim -sumnq
# -elimnq) and -nominlps, 10 hour limit.
# Usage: sbatch --cpus-per-task=32 --export=ALL,PC=32 run_senate6_2025_seedf.slurm
#   PC defaults to 64. Keep --cpus-per-task about equal to PC.
#   SEEDMAX overrides -seedmaxchildren (default 10000).
#   Task i runs contest i / 3 with fraction i % 3, so tasks 0-2 are NSW 25 at
#   0.25, 0.5, 0.75, tasks 3-5 QLD 25, and so on. Run some only with e.g.
#   --array=0-2.

#SBATCH --job-name=senate25f
#SBATCH --account=sz64
#SBATCH --array=0-17

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
#SBATCH --output=senate25f-%A_%a.out
#SBATCH --error=senate25f-%A_%a.err


BIN=$HOME/sz64/marginstv/cpp/build/marginstv
DATA=$HOME/sz64_scratch/data
PC=${PC:-64}
SEEDMAX=${SEEDMAX:-10000}

FILES=(FedAus25/FederalSenate2025NSW.json FedAus25/FederalSenate2025QLD.json
       FedAus25/FederalSenate2025SA.json FedAus25/FederalSenate2025TAS.json
       FedAus25/FederalSenate2025VIC.json FedAus25/FederalSenate2025WA.json)
NAMES=('NSW 25' 'QLD 25' 'SA 25' 'TAS 25' 'VIC 25' 'WA 25')
FRACS=(0.25 0.5 0.75)
TAGS=(f025 f050 f075)

i=$SLURM_ARRAY_TASK_ID
c=$((i / 3))
f=$((i % 3))
FILE=${FILES[$c]}
SEEDF=${FRACS[$f]}
TAG=${TAGS[$f]}

"$BIN" -d "$DATA/$FILE" -s 6 -displayname "${NAMES[$c]} ${TAG}" \
    -pc "$PC" -g 0.01 -agap 0 -m -limit 36000 \
    -lse -eqlbc -dlbc -useqprefix -prec_et \
    -sumq -multielim -sumnq -elimnq -nominlps \
    -weakseed -seedf "$SEEDF" -seedmaxchildren "$SEEDMAX" \
    -threads "$SLURM_CPUS_PER_TASK" \
    -log "log_${FILE//\//}_M3_pc${PC}_weakseed_${TAG}_cpp.log" \
    | tail -n 1 > "summary6_2025_weakseed_${TAG}_pc${PC}_${c}.csv"
