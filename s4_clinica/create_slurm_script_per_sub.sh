#!/bin/bash

# Create per-subject Clinica Slurm scripts from a template.
#
# Assumes this script lives alongside:
#   - adni_clinica.slurm          (template Slurm script)
#   - adni_subs.txt               (one subject ID per line)
#
# Usage:
#   bash create_slurm_script_per_sub.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

SUB_LIST="adni_subs.txt"
TEMPLATE="adni_clinica.slurm"

if [[ ! -f "$SUB_LIST" ]]; then
  echo "[create_slurm_script_per_sub] Subject list not found: $SUB_LIST" >&2
  exit 1
fi

if [[ ! -f "$TEMPLATE" ]]; then
  echo "[create_slurm_script_per_sub] Template Slurm file not found: $TEMPLATE" >&2
  exit 1
fi

while IFS= read -r sub; do
  [[ -z "$sub" ]] && continue
  echo "$sub"
  echo "$sub" > "${sub}.txt"

  out_slurm="${sub}_adni_clinica.slurm"
  cp "$TEMPLATE" "$out_slurm"

  # Use a portable sed -i implementation (macOS/BSD vs GNU):
  if sed --version >/dev/null 2>&1; then
    # GNU sed
    sed -i "s|job-name=ADNI|job-name=ADNI_${sub}|" "$out_slurm"
    sed -i "s|cl-ADNI|cl-ADNI_${sub}|" "$out_slurm"
    sed -i "s|adni_subs|${sub}|" "$out_slurm"
    sed -i "s|adni_clinica_log|adni_${sub}_clinica_log|" "$out_slurm"
  else
    # BSD/macOS sed requires a backup suffix, use inline edit with temp backup
    sed -i '' "s|job-name=ADNI|job-name=ADNI_${sub}|" "$out_slurm"
    sed -i '' "s|cl-ADNI|cl-ADNI_${sub}|" "$out_slurm"
    sed -i '' "s|adni_subs|${sub}|" "$out_slurm"
    sed -i '' "s|adni_clinica_log|adni_${sub}_clinica_log|" "$out_slurm"
  fi

done < "$SUB_LIST"


# path2slurmScripts=$1   # path to dir where SLURM scripts will be created
# path2subjectList=$2   # path to text file with list of subject IDs

# script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

# path2slurmTemplate="${3:-$script_dir}"

# [[ -d "$path2slurmTemplate" || -f "$path2slurmTemplate" ]] \
#   || { echo "Invalid path2slurmTemplate: $path2slurmTemplate" >&2; exit 1; }


# #check that paths exist
# if [ ! -d ${path2slurmScripts} ]; then
#     echo "Error: Path to SLURM scripts directory ${path2slurmScripts} does not exist."
#     exit 1
# fi

# if [ ! -f ${path2subjectList} ]; then
#     echo "Error: Path to subject list file ${path2subjectList} does not exist."
#     exit 1
# fi  


# for i in `cat ${path2subjectList}`
# do
#     echo ${i}
#     echo ${i} > ${path2slurmScripts}/${i}.txt
#     for m in func anat dti; do
#         cp ${path2slurmTemplate}/adni_clinica_${m}.slurm ${path2slurmScripts}/${i}_adni_clinica_${m}.slurm
#         sed -i "s|job-name=adni2bids|job-name=${i}_${m}|" ${path2slurmScripts}/${i}_adni_clinica_${m}.slurm
#         sed -i "s|ADNI-subID|${i}|" ${path2slurmScripts}/${i}_adni_clinica_${m}.slurm
#         sed -i "s|sub2convert|${i}|" ${path2slurmScripts}/${i}_adni_clinica_${m}.slurm
#         sed -i "s|adni_clinica_log|${i}_${m}_log|" ${path2slurmScripts}/${i}_adni_clinica_${m}.slurm
#     done

# done