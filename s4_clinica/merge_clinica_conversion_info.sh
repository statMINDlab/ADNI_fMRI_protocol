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

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"


CONFIG_PATH=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --config)
      CONFIG_PATH="$2"
      shift 2
      ;;
    --path2conversionInfo)
      CONVERSION_INFO_DIR="$2"
      shift 2
      ;;
    -h|--help)
      echo "Can be called with a --config argument to specify a config YAML \
        file or with a --path2conversionInfo argument to specify the full path to the \
        directory clinica conversion_info is stored." >&2
      echo "Usage: $0 [--config /path/to/config.yaml] [--path2conversionInfo /path/to/conversion_info/dir]" >&2

      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      echo "Usage: $0 [--config /path/to/config.yaml]" >&2
      exit 1
      ;;
  esac
done

if [[ -n "${CONFIG_PATH}" ]]; then
  if [[ ! -f "${CONFIG_PATH}" ]]; then
    echo "[merge_clinica_conversion_info] Specified config file does not exist: ${CONFIG_PATH}" >&2
    exit 1
  fi
  echo "sourcing config from: ${CONFIG_PATH}"
  cd ${SCRIPT_DIR}/..
  CONVERSION_INFO_DIR=$(python -m utils.config_tools paths.clinica_conversion_info_dir --config "${CONFIG_PATH}")
fi

if [[ -z "${CONVERSION_INFO_DIR:-}" ]]; then
  echo "[merge_clinica_conversion_info] specified path to conversion_info is empty or not set in config" >&2
  exit 1
elif [[ ! -d "${CONVERSION_INFO_DIR}" ]]; then
  echo "[merge_clinica_conversion_info] specified conversion_info directory does not exist: ${CONVERSION_INFO_DIR}" >&2
  exit 1
fi

merged_output_dir="${CONVERSION_INFO_DIR}/conversion_info_merged"
mkdir -p "${merged_output_dir}"

# call python merge_clinica_conversion_info.py script with appropriate args
python ${SCRIPT_DIR}/merge_clinica_conversion_info.py \
  --root "${CONVERSION_INFO_DIR}" \
  --out "${merged_output_dir}"
