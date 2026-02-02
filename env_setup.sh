#!/usr/bin/env bash
# env_setup.sh -- Source to export pipeline env vars and load HPC modules.
# Edit the variables in the "USER CONFIG" section below before sourcing.
#
# Usage (after editing top-of-file values):
#   source env_setup.sh
#
# The script must be sourced so exports and activations persist in your shell.

# ========================
# === USER CONFIG (edit) =
# ========================
# Mode: choose "python" or "conda"
#MODE="python"   # set to "python" to load HPC python module; "conda" to load HPC conda module + activate clinica env

# Required paths (set these to your project/cluster locations)
ADNI_BASE="/N/project/cfn-rady/andrea-dev/ADNI"                        # e.g. /N/project/ADNI
REPO_ROOT="/N/project/cfn-rady/andrea-dev/ADNI/code/ADNI_fMRI_protocol"                    # path to repo root (contains env/env_clinica.yml)
CONFIG_PATH="/N/project/cfn-rady/andrea-dev/ADNI/code/ADNI_fMRI_protocol/config/config_adni.yaml"            # full path to pipeline YAML config (this allows multiple configs)

# Path to clinica conda environment (prefix)
PATH_TO_CLIN_ENV="/N/project/cfn-commons/neuroimaging_utils/python-envs/env_clinica_dcm2niix2024"

# HPC module names (adjust to your cluster's module names if different)
HPC_PY_MODULE="python"      # e.g. python/3.10
HPC_CONDA_MODULE="conda" # module that provides conda (e.g. anaconda, miniconda, conda)

# ========================
# === End USER CONFIG ====
# ========================
## After this point, no touchies unless you know what you're doing! ##

# ------------------------
_info(){ printf '\e[32m[INFO]\e[0m %s\n' "$*"; }
_warn(){ printf '\e[33m[WARN]\e[0m %s\n' "$*"; }
_err(){ printf '\e[31m[ERROR]\e[0m %s\n' "$*"; }

# Ensure script is sourced (so exports persist); if executed directly, warn and continue but advise sourcing.
# (We cannot reliably force a return when executed directly, but we recommend sourcing.)
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  _warn "It looks like you executed the script directly. To export variables into your shell please: source env_setup.sh"
fi

# Check for module command (assume available)
if ! command -v module >/dev/null 2>&1; then
  _err "'module' command not found. This script assumes HPC environment modules are available. Aborting."
  return 1 2>/dev/null || exit 1
fi

# # Validate MODE
# if [ "$MODE" != "python" ] && [ "$MODE" != "conda" ]; then
#   _err "MODE must be set to either 'python' or 'conda' in the script header. Current: '$MODE'"
#   return 1 2>/dev/null || exit 1
# fi

# Basic validation of required paths (no interactive prompting)
_missing=0
[ -z "$ADNI_BASE" ] && _err "ADNI_BASE is empty" && _missing=1
[ -z "$REPO_ROOT" ] && _err "REPO_ROOT is empty" && _missing=1
[ -z "$CONFIG_PATH" ] && _err "CONFIG_PATH is empty" && _missing=1
if [ "$_missing" -ne 0 ]; then
  _err "Please edit env_setup.sh and set ADNI_BASE, REPO_ROOT, and CONFIG_PATH."
  return 1 2>/dev/null || exit 1
fi

# Export core variables
export ADNI_BASE REPO_ROOT CONFIG_PATH
export PATH_TO_CLIN_ENV

# Check config file exists
if [ ! -f "$CONFIG_PATH" ]; then
  _err "CONFIG_PATH does not exist or is not a file: $CONFIG_PATH"
  return 1 2>/dev/null || exit 1
fi

# -----------------------------
# check that clinica env is working
_info "Testing clinica conda env: will attempt to module load '$HPC_CONDA_MODULE' and activate conda env at prefix: $PATH_TO_CLIN_ENV"
# Load conda module
if ! module load "$HPC_CONDA_MODULE" 2>/dev/null; then
  _warn "module load $HPC_CONDA_MODULE failed. Ensure your cluster provides a conda/anaconda module named: $HPC_CONDA_MODULE"
fi

# Check if the prefix folder exists (this is how prefix-style conda envs are usually represented)
if [ -d "$PATH_TO_CLIN_ENV" ]; then
  _info "Conda env prefix directory exists: $PATH_TO_CLIN_ENV"
  # attempt to activate
  if command -v conda >/dev/null 2>&1; then
    # shellcheck disable=SC1090
    # ensure conda is initialised in this shell: use 'conda activate' (module should have provided it)
    if conda activate "$PATH_TO_CLIN_ENV" 2>/dev/null; then
      _info "Activated conda env: $PATH_TO_CLIN_ENV"
    else
      _warn "conda activate $PATH_TO_CLIN_ENV failed. You may need to 'module load $HPC_CONDA_MODULE' in your login shell first."
    fi
  else
    _warn "conda command not available after loading module $HPC_CONDA_MODULE."
  fi
else
  # env missing -> print the exact instructions requested
  cat <<EOF

[NOTICE] Clinica conda environment not found at:
${PATH_TO_CLIN_ENV}

To create it, run the following commands (on the cluster):

module load conda
conda env create --prefix ${PATH_TO_CLIN_ENV} --file ${REPO_ROOT}/env/env_clinica.yml

After creation you can activate with:
module load ${HPC_CONDA_MODULE}
conda activate ${PATH_TO_CLIN_ENV}

EOF
  # Do not error out hard; return non-zero so caller can detect
  return 2 2>/dev/null || exit 2
fi


# Load python module if in python mode
_info "Loading module '$HPC_PY_MODULE'"
if module load "$HPC_PY_MODULE" 2>/dev/null; then
  _info "Loaded module: $HPC_PY_MODULE"
else
  _warn "module load $HPC_PY_MODULE failed. Please ensure the module name is correct in the script header."
fi

# ensure python is available for utils.config_tools
if ! command -v python >/dev/null 2>&1; then
  _err "python not found in PATH. Ensure python is available (e.g., module load python) before sourcing this script."
  return 1 2>/dev/null || exit 1
fi

# helper to call utils.config_tools and return trimmed value
get_cfg(){
  local key="$1"
  local out
  if ! out="$(python -m utils.config_tools "$key" --config "$CONFIG_PATH" 2>/dev/null)"; then
    _warn "Failed to read $key via utils.config_tools (attempting again with visible stderr)..."
    # show error to help debugging
    python -m utils.config_tools "$key" --config "$CONFIG_PATH"
    return 1
  fi
  # trim whitespace/newline
  printf '%s' "$out" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//'
}

# list of keys to query
KEYS=(
  "paths.raw_zip_dir"
  "paths.raw_metadata_dir"
  "paths.raw_dicom_dir"
  "paths.slurm_jobs_dir"
  "paths.clinica_bids_dir"
  "paths.mriqc_output_dir"
)

# loop over keys, expand variables (~ and ${VAR}) and create directories if missing
for key in "${KEYS[@]}"; do
  raw="$(get_cfg "$key")" || { _warn "Skipping $key due to read error."; continue; }

  # remove surrounding quotes if present
  raw="${raw#\"}"; raw="${raw%\"}"
  raw="${raw#\'}"; raw="${raw%\'}"

  # Expand any ${VAR} (ADNI_BASE etc.) and ~. This uses eval; only use with trusted config.
  expanded="$(eval "echo \"$raw\"")"
  expanded="${expanded/#\~/$HOME}"

  if [ -z "$expanded" ]; then
    _warn "Expanded value for $key is empty; skipping."
    continue
  fi

  if [ -d "$expanded" ]; then
    _info "Directory exists ($key): $expanded"
  else
    _info "Creating directory ($key): $expanded"
    mkdir -p "$expanded" || { _err "Failed to create $expanded"; }
    # optional: set permissions (uncomment if desired)
    # chmod g+rwx "$expanded" 2>/dev/null || true
  fi
done



# Summary
cat <<EOF
[INFO] env_setup completed (sourced). Summary:
  ADNI_BASE         = $ADNI_BASE
  REPO_ROOT         = $REPO_ROOT
  CONFIG_PATH       = $CONFIG_PATH
  PATH_TO_CLIN_ENV  = $PATH_TO_CLIN_ENV

Derived directories were read from config and ensured to exist.
Use config with:
  ADNI_fMRI_protocol_some-script.sh --config "\$CONFIG_PATH"

EOF
