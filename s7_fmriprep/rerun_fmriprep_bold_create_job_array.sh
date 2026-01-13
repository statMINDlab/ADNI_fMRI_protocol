#!/bin/bash

# Config-driven helper to compute rerun subject list for fMRIPrep.
#
# Reads paths from config/config_adni.yaml via utils.config_tools:
#   - fmriprep.bids_dir           : BIDS root
#   - fmriprep.output_dir         : fMRIPrep derivatives root
#   - paths.fmriprep_results_root : root for results/scripts
#
# Usage:
#   bash rerun_fmriprep_bold_create_job_array.sh [--config /path/to/config.yaml]

set -euo pipefail

CONFIG_PATH=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --config)
      CONFIG_PATH="$2"
      shift 2
      ;;
    -h|--help)
      echo "Usage: $0 [--config /path/to/config.yaml]" >&2
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      echo "Usage: $0 [--config /path/to/config.yaml]" >&2
      exit 1
      ;;
  esac
done

if [[ -n "$CONFIG_PATH" ]]; then
  BIDS=$(python -m utils.config_tools fmriprep.bids_dir --config "$CONFIG_PATH")
  DERIV=$(python -m utils.config_tools fmriprep.output_dir --config "$CONFIG_PATH")
  RESULTS_ROOT=$(python -m utils.config_tools paths.fmriprep_results_root --config "$CONFIG_PATH")
else
  BIDS=$(python -m utils.config_tools fmriprep.bids_dir)
  DERIV=$(python -m utils.config_tools fmriprep.output_dir)
  RESULTS_ROOT=$(python -m utils.config_tools paths.fmriprep_results_root)
fi

OUTDIR="$RESULTS_ROOT/scripts"
REPORT="$OUTDIR/reports/fmriprep_error_report_ALL.csv"   # from the classifier

mkdir -p "$OUTDIR"

# 1) Subjects implicated by “no BOLD” or “filtered out” categories (from the CSV)
AFFECTED=$OUTDIR/subs_needing_rerun_from_report.txt
awk -F, 'NR>1 && ($5 ~ /no BOLD|filtered out/) {print $3}' "$REPORT" \
  | sed 's/"//g' \
  | sort -u > "$AFFECTED"

# 2) Subjects that HAVE BOLD on disk in BIDS
VALID_SUBS=$OUTDIR/valid_subjects_have_bold.txt
find "$BIDS" -type f -path "*/ses-*/func/*bold.nii.gz" \
 | sed -E 's#.*/(sub-[^/]+)/ses-.*#\1#' \
 | sort -u > "$VALID_SUBS"

# Intersect: affected AND valid
AFFECTED_VALID=$OUTDIR/affected_and_valid.txt
grep -F -f "$AFFECTED" "$VALID_SUBS" > "$AFFECTED_VALID" || true

# 3) Keep only those that do NOT yet have preproc outputs in derivatives
RERUN_SUBS=$OUTDIR/job_array_input_RERUN_subjects.txt
: > "$RERUN_SUBS"

while IFS= read -r sub; do
  # If any preproc BOLD exists, skip; else include
  if ! find "$DERIV/$sub" -path "*/ses-*/func/*desc-preproc_bold.nii.gz" -print -quit 2>/dev/null | grep -q .; then
    echo "$sub" >> "$RERUN_SUBS"
  fi
done < "$AFFECTED_VALID"

echo "Affected subs (from report): $(wc -l < "$AFFECTED")"
echo "Affected & have BOLD:        $(wc -l < "$AFFECTED_VALID")"
echo "Rerun list:                  $(wc -l < "$RERUN_SUBS")"
head "$RERUN_SUBS"
