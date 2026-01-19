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

# -------- script directory --------
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

# -------- defaults for optional args --------
CONFIG_PATH=""
modality=""   # unset unless provided

# -------- parse optional arguments --------
while [[ $# -gt 0 ]]; do
  case "$1" in
    --config)
      CONFIG_PATH="$2"
      shift 2
      ;;
    --path2slurmJobs)
      path2slurmJobs="$2"
      shift 2
      ;;
    --subj2submit)
      path2subjectList="$2"
      shift 2
      ;;
    --modality)
      modality="$2"
      shift 2
      ;;
    *)
      echo "Unexpected argument: $1" >&2
      echo "Usage: $0 [--config /path/to/config.yaml]" >&2
      exit 1
      ;;
  esac
done

if [[ -n "$CONFIG_PATH" ]]; then
  if [[ ! -f "$CONFIG_PATH" ]]; then
    echo "[create_dicom_dir_csv] Specified config file does not exist: $CONFIG_PATH" >&2
    exit 1
  fi
  echo "sourcing config from: $CONFIG_PATH"
  cd ${SCRIPT_DIR}/..
  DICOM_ROOT=$(python -m utils.config_tools paths.raw_dicom_dir --config "$CONFIG_PATH")
  path2slurmJobs=$(python -m utils.config_tools paths.slurm_jobs_dir --config "${CONFIG_PATH}")
  path2subjectList=$(python -m utils.config_tools paths.raw_subject_list --config "${CONFIG_PATH}")

fi

if [[ -z "${DICOM_ROOT:-}" ]]; then
  echo "[create_dicom_dir_csv] specified path to DICOMS is empty or not set in config" >&2
  exit 1
elif [[ ! -d "$DICOM_ROOT" ]]; then
  echo "[create_dicom_dir_csv] specified DICOM directory does not exist: $DICOM_ROOT" >&2
  exit 1
fi


#check that paths exist
if [ ! -d ${path2slurmJobs} ]; then
    echo "Error: [create_slurm_script_per_sub] Path to SLURM jobs directory doesn't exist: ${path2slurmJobs}" >&2
    exit 1
fi

if [ ! -f ${path2subjectList} ]; then
    echo "Error: [create_slurm_script_per_sub] Subject list not found: ${path2subjectList}" >&2
    exit 1
fi 


if [[ -n "$modality" ]]; then
  # If modality is specified, replace placeholder in the template
  # (assumes the template has a placeholder like MODALITY_PLACEHOLDER)
    if [ "${modality}" != "func" ] && [ "${modality}" != "anat" ] \
        && [ "${modality}" != "dti" ] && [ "${modality}" != "pet" ]; then
        echo "Error: Modality ${modality} is not recognized. Please use 'func', 'anat', 'dti', or 'pet'."
        exit 1
    fi
fi

if [[ -n "$modality" ]]; then

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