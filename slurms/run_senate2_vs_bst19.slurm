#!/bin/bash
# Runs the C++ program on the 2-seat Senate contests (ACT, NT; 2019, 2022, 2025)
# in two settings, one contest and setting per array task, 10 hour limit.
# MINLPs are solved at leaves in both settings.
#   tasks 0-5:  all improvements (-lse -eqlbc -dlbc -useqprefix -prec_et -sumq -multielim)
#   tasks 6-11: BST 19 (no quota in prefix, no extra lower bounds)
# Usage: sbatch --cpus-per-task=64 --export=ALL,PC=64 run_senate2_vs_bst19.slurm
#   PC defaults to 64. Keep --cpus-per-task about equal to PC.
#   Run some tasks only with e.g. --array=0,6 (ACT 19 in both settings).

#SBATCH --job-name=senate2-bst19
#SBATCH --account=sz64
#SBATCH --array=0-11

# One program per task, one thread per frontier node expanded each step
#SBATCH --ntasks=1
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=64

# Memory grows with the CPU count: 64 x 2000 MB = 128 GB
#SBATCH --mem-per-cpu=2000

# 10 hour search limit plus time to start up and write the summary
#SBATCH --time=0-11:00:00

#SBATCH --mail-user=michelle.blom@monash.edu
#SBATCH --mail-type=END
#SBATCH --mail-type=FAIL

# %A = array job id, %a = task number
#SBATCH --output=senate2-bst19-%A_%a.out
#SBATCH --error=senate2-bst19-%A_%a.err

BIN=$HOME/sz64/marginstv/cpp/build/marginstv
DATA=$HOME/sz64_scratch/data
PC=${PC:-64}

FILES=(FedAus19/FederalSenate2019ACT.json FedAus19/FederalSenate2019NT.json
       FedAus22/2022ACT.json FedAus22/2022NT.json
       FedAus25/2025ACT.json FedAus25/2025NT.json)
NAMES=('ACT 19' 'NT 19' 'ACT 22' 'NT 22' 'ACT 25' 'NT 25')
UBS=(12939 15890 11078 11412 23121 13256)

N=${#FILES[@]}
i=$((SLURM_ARRAY_TASK_ID % N))
FILE=${FILES[$i]}

if (( SLURM_ARRAY_TASK_ID < N )); then
    TAG=all
    FLAGS=(-lse -eqlbc -dlbc -useqprefix -prec_et -sumq -multielim)
else
    TAG=bst19
    FLAGS=()
fi

"$BIN" -d "$DATA/$FILE" -s 2 -displayname "${NAMES[$i]}" \
    -ub "${UBS[$i]}" -pc "$PC" -g 0.01 -agap 0 -m -limit 36000 \
    "${FLAGS[@]}" \
    -threads "$SLURM_CPUS_PER_TASK" \
    -log "log_${FILE//\//}_pc${PC}_cpp_${TAG}.log" \
    | tail -n 1 > "summary_pc${PC}_${TAG}_${i}.csv"
