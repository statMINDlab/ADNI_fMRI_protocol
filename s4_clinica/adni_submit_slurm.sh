#!/bin/bash

# adni_submit_slurm.sh
#
# Purpose: Submit per-subject Clinica SLURM job scripts.
#
# Behavior:
#  - Reads a subject list (one ID per line) and submits the corresponding SLURM job
#
# Usage:
#  bash adni_submit_slurm.sh /path/to/slurm/jobs /path/to/subjects.txt \
#       [--modality anat|func|dti|pet]

set -euo pipefail

# -------- required positional arguments --------
path2slurmJobs=$1
path2subjectList=$2
shift 2   # remove the first two args, leaving only optional flags

# -------- script directory --------
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

# -------- defaults for optional args --------
modality=""   # unset unless provided

# -------- parse optional arguments --------
while [[ $# -gt 0 ]]; do
  case "$1" in
    --modality)
      modality="$2"
      shift 2
      ;;
    *)
      echo "Unexpected argument: $1" >&2
      exit 1
      ;;
  esac
done

#check that paths exist
if [ ! -d ${path2slurmJobs} ]; then
    echo "Error: Path to SLURM scripts directory ${path2slurmJobs} does not exist."
    exit 1
fi

if [ ! -f ${path2subjectList} ]; then
    echo "Error: Path to subject list file ${path2subjectList} does not exist."
    exit 1
fi 

if [[ -n "$modality" ]]; then
    #check that modality is one of func, anat, dti
    if [ "${modality}" != "func" ] && [ "${modality}" != "anat" ] \
        && [ "${modality}" != "dti" ] && [ "${modality}" != "pet" ]; then
        echo "Error: Modality ${modality} is not recognized. Please use 'func', 'anat', 'dti', or 'pet'."
        exit 1
    fi

    for sub in `cat ${path2subjectList}`; do
        echo ${sub}
        if [ ! -f ${path2slurmJobs}/${sub}_adni_clinica_${modality}.slurm ]; then
            echo "Error: ${path2slurmJobs}/${sub}_adni_clinica_${modality}.slurm. NOT FOUND."
            continue
        fi
        sbatch ${path2slurmJobs}/${sub}_adni_clinica_${modality}.slurm
    done

else
    for sub in `cat ${path2subjectList}`; do
        echo ${sub}
        if [ ! -f ${path2slurmJobs}/${sub}_adni_clinica.slurm ]; then
            echo "Error: ${path2slurmJobs}/${sub}_adni_clinica.slurm. NOT FOUND."
            continue
        fi
        sbatch ${path2slurmJobs}/${sub}_adni_clinica.slurm
    done
fi