#!/bin/bash
#SBATCH --account=r01313
#SBATCH --mail-user=saiwolf@iu.edu
#SBATCH --partition=general
#SBATCH --job-name=mriqc_group
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=32G
#SBATCH --time=24:00:00
#SBATCH -o mriqc_group.out
#SBATCH -e mriqc_group.err

module load apptainer

## MRIQC group level script for ADNI fMRI data.
#
# Paths are read from config/config_adni.yaml via utils.config_tools:
#   - mriqc.bids_dir         : BIDS root input dir
#   - mriqc.output_dir       : MRIQC derivatives root (mounted as /out)
#   - containers.mriqc_image : Apptainer/Singularity image path for MRIQC
#
# Usage:
#   sbatch mriqc_group.slurm             # uses default config
#   sbatch --export=ALL,ADNI_CONFIG=... mriqc_group.slurm   # or set ADNI_CONFIG
#   sbatch --export=ALL,ADNI_CONFIG=...,MRIQC_DRY_RUN=1 mriqc_group.slurm   # dry-run

# Resolve paths from config (ADNI_CONFIG or default config/config_adni.yaml)
BIDS=$(python -m utils.config_tools mriqc.bids_dir)
OUT=$(python -m utils.config_tools mriqc.output_dir)
IMG=$(python -m utils.config_tools containers.mriqc_image)
DRY_RUN="${MRIQC_DRY_RUN:-0}"

if [[ -z "${BIDS:-}" || -z "${OUT:-}" || -z "${IMG:-}" ]]; then
  echo "[mriqc_group] One or more required config values are missing or empty" >&2
  echo "  mriqc.bids_dir   = '${BIDS:-}'" >&2
  echo "  mriqc.output_dir = '${OUT:-}'" >&2
  echo "  containers.mriqc_image = '${IMG:-}'" >&2
  exit 1
fi

if [[ "$DRY_RUN" -eq 1 ]]; then
  echo "[mriqc_group] (dry-run) would run MRIQC group-level on BIDS=${BIDS}, OUT=${OUT} with IMG=${IMG}" >&2
  exit 0
fi

# Run MRIQC
apptainer run \
  --bind "${BIDS}":/data:ro \
  --bind "${OUT}":/out \
  "${IMG}" \
  /data /out group \
  --no-sub \
  --verbose-reports \

