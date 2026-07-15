#!/bin/bash

# Config-driven fMRIPrep array launcher.
#
# Reads paths from config/config_adni.yaml via utils.config_tools:
#   - fmriprep.bids_dir             : BIDS root (Clinica output)
#   - fmriprep.output_dir           : fMRIPrep derivatives root (mounted as /out)
#   - fmriprep.work_dir             : fMRIPrep work dir (mounted as /work)
#   - paths.fmriprep_results_root   : root for scripts/logs/tmp_workdirs/done
#   - paths.fmriprep_heuristics_csv : CSV with subject/session heuristics (per-subject sessions)
#   - containers.fmriprep_image     : Apptainer/Singularity image path
#   - containers.freesurfer_license : FreeSurfer license file on the host
#
# Optional arguments:
#   --config PATH        Use a specific YAML config file instead of the default.
#   --subjects "A B ..." Run only these subjects (space-separated ADNI ids or
#                        BIDS labels), instead of the config heuristics CSV.
#   --subject-list FILE  Run only the subjects listed one-per-line in FILE.
#   --sessions-csv FILE  Run only specific subject/sessions. FILE is a CSV with a
#                        subject column (SUBJECT_ID/PTID/RID) and a visit column
#                        (VISCODE/VISCODE2); a per-subject fMRIPrep BIDS filter is
#                        generated so only those sessions are processed.
#   --subjects-csv FILE  Use FILE instead of paths.fmriprep_heuristics_csv.
#   --ignore-done        Do not skip subjects that already have a .done marker
#                        (use this to re-run subjects, e.g. after SliceTiming injection).
#   --dry-run            Build job scripts without loading Apptainer or submitting.
#
set -euo pipefail

HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_PATH=""
DRY_RUN=0
SUBJECTS_INLINE=""
SUBJECT_LIST_FILE=""
SESSIONS_CSV=""
SUBJECTS_CSV_OVERRIDE=""
IGNORE_DONE=0

usage() {
  echo "Usage: $0 [--config cfg.yaml] [--subjects \"002_S_0413 130_S_1234\"]" >&2
  echo "          [--subject-list FILE] [--sessions-csv FILE] [--subjects-csv FILE]" >&2
  echo "          [--ignore-done] [--dry-run]" >&2
}

# Normalize a subject token (002_S_0413 | sub-ADNI002S0413 | ADNI002S0413) to
# the canonical BIDS subject id used everywhere below: sub-ADNI002S0413.
normalize_subid() {
  local t
  t="$(printf '%s' "$1" | tr -cd '[:alnum:]' | tr '[:lower:]' '[:upper:]')"
  t="${t#SUB}"
  t="${t#ADNI}"
  printf 'sub-ADNI%s' "$t"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --config)
      CONFIG_PATH="$2"
      shift 2
      ;;
    --subjects)
      SUBJECTS_INLINE="$2"
      shift 2
      ;;
    --subject-list)
      SUBJECT_LIST_FILE="$2"
      shift 2
      ;;
    --sessions-csv)
      SESSIONS_CSV="$2"
      shift 2
      ;;
    --subjects-csv)
      SUBJECTS_CSV_OVERRIDE="$2"
      shift 2
      ;;
    --ignore-done)
      IGNORE_DONE=1
      shift 1
      ;;
    --dry-run)
      DRY_RUN=1
      shift 1
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 1
      ;;
  esac
done

if [[ -n "$CONFIG_PATH" ]]; then
  idir=$(python -m utils.config_tools fmriprep.bids_dir --config "$CONFIG_PATH")
  deriv_root=$(python -m utils.config_tools fmriprep.output_dir --config "$CONFIG_PATH")
  work_root=$(python -m utils.config_tools fmriprep.work_dir --config "$CONFIG_PATH")
  results_root=$(python -m utils.config_tools paths.fmriprep_results_root --config "$CONFIG_PATH")
  csv_path=$(python -m utils.config_tools paths.fmriprep_heuristics_csv --config "$CONFIG_PATH")
  img_path=$(python -m utils.config_tools containers.fmriprep_image --config "$CONFIG_PATH")
  fs_license=$(python -m utils.config_tools containers.freesurfer_license --config "$CONFIG_PATH")
else
  idir=$(python -m utils.config_tools fmriprep.bids_dir)
  deriv_root=$(python -m utils.config_tools fmriprep.output_dir)
  work_root=$(python -m utils.config_tools fmriprep.work_dir)
  results_root=$(python -m utils.config_tools paths.fmriprep_results_root)
  csv_path=$(python -m utils.config_tools paths.fmriprep_heuristics_csv)
  img_path=$(python -m utils.config_tools containers.fmriprep_image)
  fs_license=$(python -m utils.config_tools containers.freesurfer_license)
fi

# A CLI subject list (inline / file / sessions CSV) takes precedence over any CSV.
USE_SUBJECT_LIST=0
if [[ -n "$SUBJECTS_INLINE" || -n "$SUBJECT_LIST_FILE" || -n "$SESSIONS_CSV" ]]; then
  USE_SUBJECT_LIST=1
fi
if [[ -n "$SESSIONS_CSV" && ! -f "$SESSIONS_CSV" ]]; then
  echo "[run_fmriprep] Sessions CSV not found: $SESSIONS_CSV" >&2
  exit 1
fi
# Allow overriding the heuristics CSV without editing the config.
if [[ -n "$SUBJECTS_CSV_OVERRIDE" ]]; then
  csv_path="$SUBJECTS_CSV_OVERRIDE"
fi

if [[ -z "${idir:-}" || -z "${deriv_root:-}" || -z "${work_root:-}" || -z "${results_root:-}" ]]; then
  echo "[run_fmriprep] One or more required config values are missing or empty" >&2
  echo "  fmriprep.bids_dir           = '${idir:-}'" >&2
  echo "  fmriprep.output_dir         = '${deriv_root:-}'" >&2
  echo "  fmriprep.work_dir           = '${work_root:-}'" >&2
  echo "  paths.fmriprep_results_root = '${results_root:-}'" >&2
  exit 1
fi

# The subject source is either a CLI list or the (config/override) CSV.
if [[ "$USE_SUBJECT_LIST" -eq 0 && -z "${csv_path:-}" ]]; then
  echo "[run_fmriprep] No subjects given: set paths.fmriprep_heuristics_csv, or pass" >&2
  echo "               --subjects/--subject-list/--subjects-csv." >&2
  exit 1
fi
if [[ -n "$SUBJECT_LIST_FILE" && ! -f "$SUBJECT_LIST_FILE" ]]; then
  echo "[run_fmriprep] Subject list file not found: $SUBJECT_LIST_FILE" >&2
  exit 1
fi

if [[ ! -d "$idir" ]]; then
  echo "[run_fmriprep] BIDS root does not exist: $idir" >&2
  exit 1
fi

if [[ "$USE_SUBJECT_LIST" -eq 0 && ! -f "$csv_path" ]]; then
  echo "[run_fmriprep] Heuristics CSV not found: $csv_path" >&2
  exit 1
fi

if [[ -n "${img_path:-}" && ! -f "$img_path" ]]; then
  echo "[run_fmriprep] Container image not found at $img_path" >&2
  exit 1
fi

if [[ -n "${fs_license:-}" && ! -f "$fs_license" ]]; then
  echo "[run_fmriprep] FreeSurfer license not found at $fs_license" >&2
  exit 1
fi

export TEMPLATEFLOW_HOST_HOME="${TEMPLATEFLOW_HOST_HOME:-$HOME/.cache/templateflow}"
mkdir -p "${TEMPLATEFLOW_HOST_HOME}"

sdir="${results_root}/scripts"
logdir="${sdir}/logs"
filterdir="${sdir}/filters"
tmp_work_root="${results_root}/tmp_workdirs"
donedir="${sdir}/done"

# 2. Ensure required dirs
mkdir -p "$sdir" "$logdir" "$filterdir" "$deriv_root" "$tmp_work_root" "$donedir"

# 3. Set Apptainer image path
if [[ "$DRY_RUN" -eq 0 ]]; then
  module load apptainer
fi

# 4. Write dataset_description.json (idempotent)
cat <<EOF > "$idir/dataset_description.json"
{
  "Name": "ADNI rs-fMRI",
  "BIDSVersion": "1.10.1"
}
EOF

# 6. Build the list of subjects to run.
# maybe_add SUBID: append unless it already has a .done marker (unless --ignore-done).
pairs=()
maybe_add() {
    local subid="$1"
    [[ -z "$subid" || "$subid" == "sub-ADNI" ]] && return
    if [[ "$IGNORE_DONE" -eq 0 && -f "${donedir}/${subid}.done" ]]; then
        echo "  skipping ${subid} (already has .done; pass --ignore-done to force)" >&2
        return
    fi
    pairs+=("${subid}")
}

if [[ "$USE_SUBJECT_LIST" -eq 1 ]]; then
    echo "Building job array from the provided subject list..."
    # Subject/session CSV: write per-subject BIDS filters and take the subjects
    # from the CSV. The generated filters restrict fMRIPrep to those sessions.
    if [[ -n "$SESSIONS_CSV" ]]; then
        echo "  generating per-subject BIDS filters in ${filterdir} from ${SESSIONS_CSV}"
        if ! subid_list="$(python "$HERE/make_bids_filters.py" --sessions-csv "$SESSIONS_CSV" --filter-dir "$filterdir")"; then
            echo "[run_fmriprep] Failed to build BIDS filters from $SESSIONS_CSV" >&2
            exit 1
        fi
        while IFS= read -r subid; do
            [[ -n "$subid" ]] && maybe_add "$subid"
        done <<< "$subid_list"
    fi
    # Inline subjects (space-separated).
    if [[ -n "$SUBJECTS_INLINE" ]]; then
        for tok in $SUBJECTS_INLINE; do
            maybe_add "$(normalize_subid "$tok")"
        done
    fi
    # Subjects from a file (one per line; blanks and # comments ignored).
    if [[ -n "$SUBJECT_LIST_FILE" ]]; then
        while IFS= read -r line || [[ -n "$line" ]]; do
            line="${line%%#*}"
            line="$(printf '%s' "$line" | tr -d '[:space:]')"
            [[ -z "$line" ]] && continue
            maybe_add "$(normalize_subid "$line")"
        done < "$SUBJECT_LIST_FILE"
    fi
else
    echo "Parsing CSV to create job array..."
    while IFS=, read -r subj_raw v1 _; do
        [[ -z "$subj_raw" || -z "$v1" ]] && continue
        maybe_add "sub-ADNI${subj_raw//_/}"
    done < <(tail -n +2 "$csv_path")
fi

if [[ "${#pairs[@]}" -eq 0 ]]; then
    echo "[run_fmriprep] No subjects to run (all filtered out or already done)." >&2
    exit 1
fi
echo "  ${#pairs[@]} subject(s) queued."



# 7. Write job array input file
split_prefix="${sdir}/job_array_input_part_" # Split input into chunks of 499 (SLURM max is 500)
printf "%s\n" "${pairs[@]}" | split -l 499 - "$split_prefix"


# 8. Write job array script
for chunk_file in "${split_prefix}"*; do
  part_name=$(basename "$chunk_file")
  part_suffix="${part_name##*_}"  # e.g., 'aa', 'ab', etc.
  input_file="$chunk_file"
  job_script="${sdir}/fmriprep_array_${part_suffix}.slurm"
  num_jobs=$(wc -l < "$input_file")
  max_index=$((num_jobs - 1))

  if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "[run_fmriprep] (dry-run) would create job script $job_script with $num_jobs array entries from $input_file" >&2
    continue
  fi

  cut -d',' -f1 "$input_file" | sort -u | while IFS= read -r subid; do
    mkdir -p "${logdir}/${subid}"
  done

  echo "Submitting fMRIPrep job array part ${part_suffix} with $num_jobs entries..."

  cat <<EOF > "$job_script"
#!/bin/bash
#SBATCH --account=r01313
#SBATCH --mail-user=saiwolf@iu.edu
#SBATCH --partition=general
#SBATCH --job-name=fmriprep_array_${part_suffix}
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=32G
#SBATCH --time=80:00:00
#SBATCH --array=0-${max_index}%400
#SBATCH -o /dev/null
#SBATCH -e /dev/null # Setting it manually down below

module load apptainer

# 1. Grab the subject ID from the input file
IFS=',' read -r subid <<< \$(sed -n "\$((SLURM_ARRAY_TASK_ID + 1))p" $input_file)

logfile="${logdir}/\${subid}/log_\${SLURM_ARRAY_JOB_ID}_\${SLURM_ARRAY_TASK_ID}"
exec > "\$logfile.out"
exec 2> "\$logfile.err"

echo "Task ID: \$SLURM_ARRAY_TASK_ID"
echo "Parsed subid=\$subid"

# 2. Clean up any previous outputs from failed runs.
rm -rf "${deriv_root}/\${subid}/" 2>/dev/null || true
rm -rf "${deriv_root}/sourcedata/freesurfer/\${subid}/" 2>/dev/null || true

# 3. Create per-session log, work and freesurfer directories and filter file.
#filter_subdir="${filterdir}/\${subid}"
log_subdir="${logdir}/\${subid}"
mkdir -p "\$log_subdir"

workdir=\$(mktemp -d "${tmp_work_root}/work_\${subid}_XXXXXX")
freesurfer_dir="${deriv_root}/sourcedata/freesurfer/\${subid}"
mkdir -p "\$freesurfer_dir"

donefile="${donedir}/\${subid}.done"

# Use a per-subject BIDS filter if one was generated (--sessions-csv runs),
# so fMRIPrep only processes the requested sessions for this subject.
bids_filter_arg=""
if [ -f "${filterdir}/\${subid}_filter.json" ]; then
  bids_filter_arg="--bids-filter-file /filters/\${subid}_filter.json"
  echo "Using BIDS filter ${filterdir}/\${subid}_filter.json"
fi

# 4. Run fMRIPrep
apptainer run \\
  --cleanenv \\
  --bind ${idir}:/data:ro \\
  --bind ${filterdir}:/filters:ro \\
  --bind ${deriv_root}:/out \\
  --bind ${fs_license}:/license.txt:ro \\
  --bind ${TEMPLATEFLOW_HOST_HOME}:/opt/templateflow \\
  --bind "\$workdir":/work \\
  --bind "\$freesurfer_dir":/fsdir \\
  ${img_path} \\
  /data \\
  /out \\
  participant \\
  --participant-label \${subid} \\
  \${bids_filter_arg} \\
  --force syn-sdc \\
  --ignore fieldmaps \\
  --subject-anatomical-reference sessionwise \\
  --output-spaces MNI152NLin6Asym:res-2 MNI152NLin2009cAsym fsnative \\
  --output-spaces fsaverage:den-10k \\
  --cifti-output 91k \\
  --output-spaces func \\
  --write-graph \\
  --notrack \\
  --random-seed 357 \\
  -vv \\
  --fs-license-file /license.txt \\
  --fs-subjects-dir /fsdir \\
  --skip-bids-validation \\
  --nprocs 16 \\
  --stop-on-first-crash \\
  --work-dir "/work" \\
  --clean-workdir

# 5. Check for success and cleanup
status=\$?
if [ "\$status" -eq 0 ]; then
  echo "fMRIPrep completed successfully for \${subid}"
  touch "\$donefile"
  rm -rf "\$workdir"
  echo "Marked \${subid} as done."
else
  echo "fMRIPrep failed for \${subid} with exit code \$status"
  exit \$status
fi
EOF

  # 9. Submit job array
#  sbatch "$job_script"
done
