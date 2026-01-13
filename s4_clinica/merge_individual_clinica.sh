#!/bin/bash

# Merge per-subject Clinica BIDS outputs into a single BIDS_all tree.
#
# This script is now config-driven and reads paths from config/config_adni.yaml
# via utils.config_tools:
#   - paths.clinica_bids_individual_dir : root for per-subject BIDS outputs
#   - paths.clinica_bids_dir           : merged BIDS_all root
#   - paths.clinica_subjects_list      : text file with one subject ID per line
#
# Usage:
#   bash merge_individual_clinica.sh [--config /path/to/config.yaml]

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
  BIDS_INDIV=$(python -m utils.config_tools paths.clinica_bids_individual_dir --config "$CONFIG_PATH")
  BIDS_ALL=$(python -m utils.config_tools paths.clinica_bids_dir --config "$CONFIG_PATH")
  SUB_LIST=$(python -m utils.config_tools paths.clinica_subjects_list --config "$CONFIG_PATH")
else
  BIDS_INDIV=$(python -m utils.config_tools paths.clinica_bids_individual_dir)
  BIDS_ALL=$(python -m utils.config_tools paths.clinica_bids_dir)
  SUB_LIST=$(python -m utils.config_tools paths.clinica_subjects_list)
fi

if [[ -z "${BIDS_INDIV:-}" || -z "${BIDS_ALL:-}" || -z "${SUB_LIST:-}" ]]; then
  echo "[merge_individual_clinica] One or more required config keys are missing or empty" >&2
  echo "  paths.clinica_bids_individual_dir = '${BIDS_INDIV:-}'" >&2
  echo "  paths.clinica_bids_dir            = '${BIDS_ALL:-}'" >&2
  echo "  paths.clinica_subjects_list       = '${SUB_LIST:-}'" >&2
  exit 1
fi

if [[ ! -d "$BIDS_INDIV" ]]; then
  echo "[merge_individual_clinica] Individual BIDS directory does not exist: $BIDS_INDIV" >&2
  exit 1
fi

if [[ ! -f "$SUB_LIST" ]]; then
  echo "[merge_individual_clinica] Subject list file not found: $SUB_LIST" >&2
  exit 1
fi

mkdir -p "$BIDS_ALL/conversion_info/v0"

while IFS= read -r sub; do
  [[ -z "$sub" ]] && continue
  echo "Merging subject ${sub} BIDS folder"

  subj_src="$BIDS_INDIV/$sub"
  if [[ -d "$subj_src" ]]; then
    cp -r "$subj_src" "$BIDS_ALL/sub-${sub}"

    # Note: logic below mirrors the original script (conditions preserved).
    if [[ ! -e "$subj_src/conversion_info/v0/fmri_paths.tsv" ]]; then
      cat "$subj_src/conversion_info/v0/fmri_paths.tsv" >> "$BIDS_ALL/conversion_info/v0/fmri_paths.tsv"
    fi
    if [[ ! -e "$subj_src/conversion_info/v0/t1w_paths.tsv" ]]; then
      cat "$subj_src/conversion_info/v0/t1w_paths.tsv" >> "$BIDS_ALL/conversion_info/v0/t1w_paths.tsv"
    fi
    if [[ ! -e "$subj_src/conversion_info/v0/flair_paths.tsv" ]]; then
      cat "$subj_src/conversion_info/v0/flair_paths.tsv" >> "$BIDS_ALL/conversion_info/v0/flair_paths.tsv"
    fi
    if [[ ! -e "$subj_src/conversion_info/v0/participants.tsv" ]]; then
      cat "$subj_src/conversion_info/v0/participants.tsv" >> "$BIDS_ALL/conversion_info/v0/participants.tsv"
    fi
  else
    echo "Subject ${sub} BIDS folder not found under ${BIDS_INDIV}, skipping." >&2
  fi

done < "$SUB_LIST"
