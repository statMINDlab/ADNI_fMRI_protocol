#!/bin/bash
#
# Create a CSV listing all DICOM directories for downstream QC.
# The root DICOM directory is read from config/config_adni.yaml
# (paths.raw_dicom_dir) via the utils.config_tools helper.
# or provided as an argument with the --path2dicom option
#
# Optional arguments:
#   --config PATH   Use a specific YAML config file instead of the default.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"


CONFIG_PATH=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --config)
      CONFIG_PATH="$2"
      shift 2
      ;;
    --path2dicom)
      DICOM_ROOT="$2"
      shift 2
      ;;
    -h|--help)
      echo "Can be called with a --config argument to specify a config YAML \
        file or with a --path2dicom argument to specify the full path to the \
        directory where DICOMs have been unzipped." >&2
      echo "Usage: $0 [--config /path/to/config.yaml] [--path2dicom /path/to/dicom/dir]" >&2

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
  if [[ ! -f "$CONFIG_PATH" ]]; then
    echo "[create_dicom_dir_csv] Specified config file does not exist: $CONFIG_PATH" >&2
    exit 1
  fi
  echo "sourcing config from: $CONFIG_PATH"
  cd ${SCRIPT_DIR}/..
  echo "here we are: $(pwd)"
  DICOM_ROOT=$(python -m utils.config_tools paths.raw_dicom_dir --config "$CONFIG_PATH")
fi

if [[ -z "${DICOM_ROOT:-}" ]]; then
  echo "[create_dicom_dir_csv] specified path to DICOMS is empty or not set in config" >&2
  exit 1
elif [[ ! -d "$DICOM_ROOT" ]]; then
  echo "[create_dicom_dir_csv] specified DICOM directory does not exist: $DICOM_ROOT" >&2
  exit 1
fi

cd ${DICOM_ROOT}

:> unzipped_dicom_dirs_inventory.csv
echo "Subject,Description,Acq Date,ImageID" >> unzipped_dicom_dirs_inventory.csv

for sub in *; do
  [[ -d "$sub" ]] || continue
  echo "Inventorying subject: ${sub}"

  for series in "$sub"/*; do
    [[ -d "$series" ]] || continue
    series_name=$(basename "$series")
    clean_series=${series_name//,/--}  ## found Series Names with comas and that breaks the CSV files. 

    for date in "$series"/*; do
      [[ -d "$date" ]] || continue
      date_name=$(basename "$date")

      for imgID in "$date"/*; do
        [[ -d "$imgID" ]] || continue
        imgID_name=$(basename "$imgID")

        echo "${sub},${clean_series},${date_name},${imgID_name}" >> unzipped_dicom_dirs_inventory.csv

      done
    done
  done
done

echo "CSV file created: unzipped_dicom_dirs_inventory.csv"
