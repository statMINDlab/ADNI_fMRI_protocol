#!/bin/bash

# create_slurm_script_per_sub.sh
#
# Purpose: Create per-subject Clinica SLURM job scripts from a template.
#
# Behavior:
#  - Reads a subject list (one ID per line) and copies a Slurm template for
#    each subject, performing simple placeholder substitutions (job name,
#    subject ID, log names). Optionally sets modality-specific filenames.
#
# Assumptions:
#  - The template Slurm file contains predictable placeholders such as
#    `job-name=ADNI`, `cl-ADNI`, `adni_subs`, and `adni_clinica_log` which
#    this script replaces for each subject.
#
# Usage:
#  bash create_slurm_script_per_sub.sh /path/to/output/jobs /path/to/subjects.txt \
#      [--template /path/to/adni_clinica.slurm] [--modality anat|func|dti|pet]
#
# Examples:
#  Create default scripts using the template next to this script:
#    bash create_slurm_script_per_sub.sh /scratch/adni_jobs adni_subs.txt
#
#  Create modality-specific scripts using an explicit template:
#    bash create_slurm_script_per_sub.sh /scratch/adni_jobs adni_subs.txt \
#      --template /home/user/templates/adni_clinica.slurm --modality func
#
# Notes:
#  - This script is portable between GNU sed and BSD/macOS sed; it uses
#    a simple feature-detect to choose the correct inline-edit invocation.

set -euo pipefail

# # -------- required positional arguments --------
# path2slurmJobs=$1
# path2subjectList=$2
# shift 2   # remove the first two args, leaving only optional flags

# -------- script directory --------
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

# -------- defaults for optional args --------
CONFIG_PATH=""
path2slurmTemplate="${SCRIPT_DIR}/adni_clinica.slurm"
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
    --template)
      path2slurmTemplate="$2"
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
  path2slurmTemplate=$(python -m utils.config_tools paths.slurm_template --config "${CONFIG_PATH}")

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

if [[ ! -f "$path2slurmTemplate" ]]; then
  echo "[create_slurm_script_per_sub] Template Slurm file not found: $path2slurmTemplate" >&2; \
  exit 1; 
fi 

if [[ -n "$modality" ]]; then
  # If modality is specified, replace placeholder in the template
  # (assumes the template has a placeholder like MODALITY_PLACEHOLDER)
  if [[ "$modality" != "func" && "$modality" != "anat" && "$modality" != "dti" && "$modality" != "pet" ]]; then
    echo "Error: [create_slurm_script_per_sub] Modality ${modality} is not recognized. Please use 'func', 'anat', 'dti', or 'pet'." >&2
    exit 1
  fi
fi

while IFS= read -r sub; do
  [[ -z "$sub" ]] && continue
  echo "$sub"
  echo ${sub} > "${path2slurmJobs}/${sub}.txt"

  if [[ -n "$modality" ]]; then

    out_slurm="${path2slurmJobs}/${sub}_adni_clinica_${modality}.slurm"
    cp ${path2slurmTemplate} ${out_slurm}

    if sed --version >/dev/null 2>&1; then
      # GNU sed
        sed -i "s|job-name=ADNI|job-name=${sub}_${modality}|" ${out_slurm}
        sed -i "s|cl-ADNI|${sub}|" ${out_slurm}
        sed -i "s|adni_subs|${sub}|" ${out_slurm}
        sed -i "s|adni_clinica_log|${sub}_${modality}_log|" ${out_slurm}
      # BSD/macOS sed requires a backup suffix, use inline edit with temp backup
    else
        sed -i '' "s|job-name=ADNI|job-name=${sub}_${modality}|" ${out_slurm}
        sed -i '' "s|cl-ADNI|${sub}|" ${out_slurm}
        sed -i '' "s|adni_subs|${sub}|" ${out_slurm}
        sed -i '' "s|adni_clinica_log|${sub}_${modality}_log|" ${out_slurm}
    fi
  else
    out_slurm="${path2slurmJobs}/${sub}_adni_clinica.slurm"
    cp ${path2slurmTemplate} ${out_slurm}
    # Use a portable sed -i implementation (macOS/BSD vs GNU):
    if sed --version >/dev/null 2>&1; then
      # GNU sed
      sed -i "s|job-name=ADNI|job-name=ADNI_${sub}|" "$out_slurm"
      sed -i "s|cl-ADNI|cl-ADNI_${sub}|" "$out_slurm"
      sed -i "s|adni_subs|${sub}|" "$out_slurm"
      sed -i "s|adni_clinica_log|${sub}_clinica_log|" "$out_slurm"
    else
      # BSD/macOS sed requires a backup suffix, use inline edit with temp backup
      sed -i '' "s|job-name=ADNI|job-name=ADNI_${sub}|" "$out_slurm"
      sed -i '' "s|cl-ADNI|cl-ADNI_${sub}|" "$out_slurm"
      sed -i '' "s|adni_subs|${sub}|" "$out_slurm"
      sed -i '' "s|adni_clinica_log|${sub}_clinica_log|" "$out_slurm"
    fi
  fi
  
done < "${path2subjectList}"
echo "[create_slurm_script_per_sub] Finished creating Slurm scripts in: ${path2slurmJobs}"