#!/bin/bash
#
# Create a list of subject from the unzipped DICOM directories. 
# This is the list of subjects that will be used for clinica conversions.
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
    --path2subjectlist)
      DICOM_SUBJECT_LIST="$2"
      shift 2
      ;;
    -h|--help)
      echo "Can be called with a --config argument to specify a config YAML \
        file or with a --path2dicom argument to specify the full path to the \
        directory where DICOMs have been unzipped, and a --path2subjectlist argument to 
        specify the full path to save the subject list." >&2
      echo "Usage: $0 [--config /path/to/config.yaml] [--path2dicom /path/to/dicom/dir] [--path2subjectlist /path/to/subject/list]" >&2

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
    echo "[create_dicom_dir_csv] Specified config file does not exist: ${CONFIG_PATH}" >&2
    exit 1
  fi
  echo "sourcing config from: ${CONFIG_PATH}"
  cd ${SCRIPT_DIR}/..   # don't like to CD inside scripts but utils.config_tools needs to be run from the project root
                        # not sure why, but it won't work if provide path: $CONFIG_PATH.utils.config_tools paths.raw_dicom_dir
  DICOM_ROOT=$(python -m utils.config_tools paths.raw_dicom_dir --config "${CONFIG_PATH}")
  DICOM_SUBJECT_LIST=$(python -m utils.config_tools paths.raw_subject_list --config "${CONFIG_PATH}")
fi

if [[ -z "${DICOM_ROOT:-}" ]]; then
  echo "[create_dicom_dir_csv] A path to dicom directories is not set. Please specify in config or with --path2dicom flag" >&2
  exit 1
elif [[ ! -d "${DICOM_ROOT}" ]]; then
  echo "[create_dicom_dir_csv] specified DICOM directory does not exist: ${DICOM_ROOT}" >&2
  exit 1
fi

if [[ -z "${DICOM_SUBJECT_LIST:-}" ]]; then
  echo "[create_dicom_dir_csv] A path to a subject list is not set. Please specify in config or with --path2subjectlist flag" >&2
  exit 1
elif [[ ! -d $(dirname "${DICOM_SUBJECT_LIST}") ]]; then
  echo "[create_dicom_dir_csv] specified subject list directory does not exist: $(dirname "${DICOM_SUBJECT_LIST}")" >&2
  exit 1
fi

for sub in ${DICOM_ROOT}/*; do
  [[ -d "$sub" ]] || continue
  sub_name=$(basename "$sub")
  # check that sub_name is formatted as 123_S_12345
  if ! [[ "$sub_name" =~ ^[0-9]{3}_S_[0-9]{4,5}$ ]]; then
      echo "Warning: Subject directory name ${sub_name} does not match expected format XXX_S_XXXX[X]. Skipping."
      continue
  fi  
  echo "Adding subject to list: ${sub_name}"
  echo "${sub_name}" >> ${DICOM_SUBJECT_LIST}

done

echo "Subject list created: ${DICOM_SUBJECT_LIST}"
