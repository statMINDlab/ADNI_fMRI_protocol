#!/bin/bash
#SBATCH --account=r01313
#SBATCH --mail-user=saiwolf@iu.edu
#SBATCH --partition=general
#SBATCH --job-name=fmriprep_rerun_syn_subs
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=32G
#SBATCH --time=36:00:00
#SBATCH --array=0-231%400
#SBATCH -o /dev/null
#SBATCH -e /dev/null

module load apptainer


# -------- Paths --------
BASE=/N/project/statadni/20250922_Saige
BIDS=${BASE}/adni_db/bids/participants
DERIV_ROOT=${BASE}/fmriprep/results/derivatives
LOGS=${BASE}/fmriprep/results/scripts/logs
DONE=${BASE}/fmriprep/results/scripts/done
IMG=${BASE}/singularity_images/fmriprep-25.2.3.simg
FS_LICENSE=${BASE}/fmriprep/results/license.txt
PAIRS=${BASE}/fmriprep/results/scripts/job_array_input_RERUN_nosyn_subjects.txt

# -------- Read subject for this array task --------
subid=$(sed -n "$((SLURM_ARRAY_TASK_ID + 1))p" "$PAIRS" | tr -d '\r')
if [[ -z "${subid}" ]]; then
  echo "No subject for task ${SLURM_ARRAY_TASK_ID}; exiting."
  exit 0
fi

logfile="${LOGS}/${subid}/rerun_nosyn_${SLURM_ARRAY_JOB_ID}_${SLURM_ARRAY_TASK_ID}"
mkdir -p "$(dirname "$logfile")" "$DONE"
exec >  "${logfile}.out"
exec 2> "${logfile}.err"

echo "Task: ${SLURM_ARRAY_TASK_ID}"
echo "Subject: ${subid}"

# -------- Discover sessions that actually contain BOLD --------
mapfile -t SESSIONS < <(
  find "${BIDS}/${subid}" -maxdepth 3 -type f -path "*/ses-*/func/*bold.nii.gz" 2>/dev/null \
  | sed -E 's#.*/ses-([^/]+)/func/.*#\1#' \
  | sort -u
)
echo "BOLD sessions detected: ${SESSIONS[*]:-<none>}"

if ((${#SESSIONS[@]} == 0)); then
  echo "No BOLD found on disk for ${subid}. Skipping."
  exit 0
fi

# -------- Per-run work + FS directory (no deletions) --------
workdir=$(mktemp -d "${BASE}/fmriprep/results/tmp_workdirs/work_${subid}_XXXXXX")
freesurfer_dir="${DERIV_ROOT}/sourcedata/freesurfer/${subid}"
mkdir -p "${freesurfer_dir}"

echo "Workdir: ${workdir}"
echo "FS subjects dir: ${freesurfer_dir}"
echo "Image: ${IMG}"


# -------- Run fMRIPrep --------

apptainer run \
  --cleanenv \
  --bind "${BIDS}":/data:ro \
  --bind "${DERIV_ROOT}":/out \
  --bind "${FS_LICENSE}":/license.txt:ro \
  --bind "/N/u/${USER}/Quartz/.cache/templateflow":/opt/templateflow \
  --bind "${workdir}":/work \
  --bind "${freesurfer_dir}":/fsdir \
  "${IMG}" \
  /data /out participant \
  --participant-label "${subid}" \
  --session-label "${SESSIONS[@]}" \
  --ignore fieldmaps \
  --subject-anatomical-reference sessionwise \
  --output-spaces MNI152NLin6Asym:res-2 \
  --output-spaces MNI152NLin2009cAsym \
  --output-spaces fsnative \
  --output-spaces fsaverage:den-10k \
  --output-spaces func \
  --cifti-output 91k \
  --write-graph \
  --notrack \
  --random-seed 357 \
  -vv \
  --fs-license-file /license.txt \
  --fs-subjects-dir /fsdir \
  --skip-bids-validation \
  --nprocs 16 \
  --stop-on-first-crash \
  --work-dir "/work" \

status=$?
if [[ "$status" -eq 0 ]]; then
  echo "Success: ${subid} (sessions: ${SESSIONS[*]})"
  touch "${DONE}/${subid}.done"
  # No deletions: preserving workdir & outputs
else
  echo "Failed: ${subid} (exit ${status})"
  exit "$status"
fi
