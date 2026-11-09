#!/bin/bash
# Runs the C++ program on the 6-seat Senate contests (2019, 2022, 2025),
# one contest per array task, with every bound improvement (-sumq
# -multielim -sumnq -elimnq) and -nominlps, 10 hour limit.
# Usage: sbatch --cpus-per-task=32 --export=ALL,PC=32 run_senate6.slurm
#   PC defaults to 64. Keep --cpus-per-task about equal to PC.
#   Run some contests only with e.g. --array=0,2 (numbers match the lists below).

#SBATCH --job-name=senate6
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
#SBATCH --output=senate6-%A_%a.out
#SBATCH --error=senate6-%A_%a.err


BIN=$HOME/sz64/marginstv/cpp/build/marginstv
DATA=$HOME/sz64_scratch/data
PC=${PC:-64}

FILES=(FedAus19/FederalSenate2019NSW.json FedAus19/FederalSenate2019QLD.json
       FedAus19/FederalSenate2019SA.json FedAus19/FederalSenate2019TAS.json
       FedAus19/FederalSenate2019VIC.json FedAus19/FederalSenate2019WA.json
       FedAus22/FederalSenate2022NSW.json
       FedAus22/FederalSenate2022QLD.json FedAus22/FederalSenate2022SA.json
       FedAus22/FederalSenate2022TAS.json FedAus22/FederalSenate2022VIC.json
       FedAus22/FederalSenate2022WA.json
       FedAus25/FederalSenate2025NSW.json FedAus25/FederalSenate2025QLD.json
       FedAus25/FederalSenate2025SA.json FedAus25/FederalSenate2025TAS.json
       FedAus25/FederalSenate2025VIC.json FedAus25/FederalSenate2025WA.json)
NAMES=('NSW 19' 'QLD 19' 'SA 19' 'TAS 19' 'VIC 19' 'WA 19'
       'NSW 22' 'QLD 22' 'SA 22' 'TAS 22' 'VIC 22' 'WA 22'
       'NSW 25' 'QLD 25' 'SA 25' 'TAS 25' 'VIC 25' 'WA 25')

i=$SLURM_ARRAY_TASK_ID
FILE=${FILES[$i]}

"$BIN" -d "$DATA/$FILE" -s 6 -displayname "${NAMES[$i]}" \
    -pc "$PC" -g 0.01 -agap 0 -m -limit 36000 \
    -lse -eqlbc -dlbc -useqprefix -prec_et \
    -sumq -multielim -sumnq -elimnq -nominlps \
    -threads "$SLURM_CPUS_PER_TASK" \
    -log "log_${FILE//\//}_M3_pc${PC}_allimp_cpp.log" \
    | tail -n 1 > "summary6_allimp_pc${PC}_${i}.csv"
