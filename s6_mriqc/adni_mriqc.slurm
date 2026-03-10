#!/bin/bash

# Config-driven MRIQC job array setup script for ADNI fMRI data.
#
# This script will create job_array_input files and corresponding SLURM job
# array scripts to process subjects in batches of 499.
# Paths are read from config/config_adni.yaml via utils.config_tools:
#   - mriqc.bids_dir             : BIDS root input dir
#   - mriqc.output_dir           : MRIQC derivatives root (mounted as /out)
#   - mriqc.work_dir             : MRIQC work dir (mounted as /work)
  #   - paths.mriqc_results_root   : root for scripts/logs/tmp_workdirs/done
  #   - qc.heuristics_final_table  : CSV with subject/session info
  #   - containers.mriqc_image     : Apptainer/Singularity image path for MRIQC
#
# Usage:
#   bash adni_mriqc.slurm [--config /path/to/config.yaml]

set -euo pipefail

CONFIG_PATH=""
DRY_RUN=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --config)
      CONFIG_PATH="$2"
      shift 2
      ;;
    --dry-run)
      DRY_RUN=1
      shift 1
      ;;
    -h|--help)
      echo "Usage: $0 [--config /path/to/config.yaml] [--dry-run]" >&2
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      echo "Usage: $0 [--config /path/to/config.yaml] [--dry-run]" >&2
      exit 1
      ;;
  esac
done

if [[ -n "$CONFIG_PATH" ]]; then
  idir=$(python -m utils.config_tools mriqc.bids_dir --config "$CONFIG_PATH")
  deriv_root=$(python -m utils.config_tools mriqc.output_dir --config "$CONFIG_PATH")
  work_root=$(python -m utils.config_tools mriqc.work_dir --config "$CONFIG_PATH")
  results_root=$(python -m utils.config_tools paths.mriqc_results_root --config "$CONFIG_PATH")
  csv_path=$(python -m utils.config_tools qc.heuristics_final_table --config "$CONFIG_PATH")
  img_path=$(python -m utils.config_tools containers.mriqc_image --config "$CONFIG_PATH")
else
  idir=$(python -m utils.config_tools mriqc.bids_dir)
  deriv_root=$(python -m utils.config_tools mriqc.output_dir)
  work_root=$(python -m utils.config_tools mriqc.work_dir)
  results_root=$(python -m utils.config_tools paths.mriqc_results_root)
  csv_path=$(python -m utils.config_tools qc.heuristics_final_table)
  img_path=$(python -m utils.config_tools containers.mriqc_image)
fi

if [[ -z "${idir:-}" || -z "${deriv_root:-}" || -z "${work_root:-}" || -z "${results_root:-}" || -z "${csv_path:-}" ]]; then
  echo "[adni_mriqc] One or more required config values are missing or empty" >&2
  echo "  mriqc.bids_dir           = '${idir:-}'" >&2
  echo "  mriqc.output_dir         = '${deriv_root:-}'" >&2
  echo "  mriqc.work_dir           = '${work_root:-}'" >&2
  echo "  paths.mriqc_results_root = '${results_root:-}'" >&2
  echo "  qc.heuristics_final_table = '${csv_path:-}'" >&2
  exit 1
fi

if [[ ! -d "$idir" ]]; then
  echo "[adni_mriqc] BIDS root does not exist: $idir" >&2
  exit 1
fi

if [[ ! -f "$csv_path" ]]; then
  echo "[adni_mriqc] Heuristics CSV not found: $csv_path" >&2
  exit 1
fi

if [[ -n "${img_path:-}" ]]; then
  mkdir -p "$(dirname "$img_path")"
fi

# Mirror the configured MRIQC output_dir for use inside the job array script.
odir="$deriv_root"

# 1. Set derived paths
sdir="${results_root}/scripts"
logdir="${sdir}/logs"
tmp_work_root="${results_root}/tmp_workdirs"
donedir="${sdir}/done"

# 2. Ensure required dirs
mkdir -p "$sdir" "$logdir" "$deriv_root" "$tmp_work_root" "$donedir"

# 3. Set Apptainer image path and ensure it exists (optional auto-build)
if [[ "$DRY_RUN" -eq 0 ]]; then
  module load apptainer
  # If the specified image does not exist, try building from the matching MRIQC Docker image.
  if [[ -n "${img_path:-}" && ! -f "$img_path" ]]; then
    echo "[adni_mriqc] MRIQC image not found at $img_path; attempting to build from docker://nipreps/mriqc:24.0.2" >&2
    apptainer build "$img_path" "docker://nipreps/mriqc:24.0.2"
  fi
fi


# 4. Extract subject id
pairs=()
echo "Parsing CSV to create job array..."
while IFS=, read -r subj_raw v1 _; do
    [[ -z "$subj_raw" || -z "$v1" ]] && continue
    subid="sub-ADNI${subj_raw//_/}"
    donefile="${donedir}/${subid}.done"
    if [ ! -f "$donefile" ]; then
        pairs+=("${subid}")
    fi
done < <(tail -n +2 "$csv_path")


# 5. Write job array input file
split_prefix="${sdir}/job_array_input_part_" # Split input into chunks of 499 (SLURM max is 500)
printf "%s\n" "${pairs[@]}" | split -l 499 - "$split_prefix"


# 6. Write job array script
for chunk_file in "${split_prefix}"*; do
  part_name=$(basename "$chunk_file")
  part_suffix="${part_name##*_}"  # e.g., 'aa', 'ab', etc.
  input_file="$chunk_file"
  job_script="${sdir}/mriqc_array_${part_suffix}.slurm"
  num_jobs=$(wc -l < "$input_file")
  max_index=$((num_jobs - 1))

  if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "[adni_mriqc] (dry-run) would create job script $job_script with $num_jobs array entries from $input_file" >&2
    continue
  fi

  cut -d',' -f1 "$input_file" | sort -u | while IFS= read -r subid; do
    mkdir -p "${logdir}/${subid}"
  done

  echo "Submitting MRIQC job array part ${part_suffix} with $num_jobs entries..."

  cat <<EOF > "$job_script"
#!/bin/bash
#SBATCH --account=r01313
#SBATCH --mail-user=saiwolf@iu.edu
#SBATCH --partition=general
#SBATCH --job-name=mriqc_array_${part_suffix}
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=32G
#SBATCH --time=24:00:00
#SBATCH --array=0-${max_index}%499
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
rm -rf "${odir}/derivatives/\${subid}/" 2>/dev/null || true

# 3. Create log and work directories.
log_subdir="${logdir}/\${subid}"
mkdir -p "\$log_subdir"

workdir=\$(mktemp -d "${tmp_work_root}/work_\${subid}_XXXXXX")
donefile="${donedir}/\${subid}.done"

# 4. Run MRIQC
apptainer run \\
  --bind ${idir}:/data:ro \\
  --bind ${deriv_root}:/out \\
  --bind "\$workdir":/work \\
  ${img_path} \\
  /data \\
  /out \\
  participant \\
  --participant-label \${subid} \\
  --nprocs 16 \\
  --omp-nthreads 8 \\
  --work-dir "/work" \\
  --no-sub \\

# 5. Check for success and cleanup
status=\$?
if [ "\$status" -eq 0 ]; then
  echo "MRIQC completed successfully for \${subid}"
  touch "\$donefile"
  rm -rf "\$workdir"
  echo "Marked \${subid} as done."
else
  echo "MRIQC failed for \${subid} with exit code \$status"
  exit \$status
fi
EOF

  # 9. Submit job array
#  sbatch "$job_script"
done

