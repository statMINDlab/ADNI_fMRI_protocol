#!/usr/bin/env bash

# shellcheck source=/dev/null
#SBATCH --partition=general
#SBATCH --account=r00240
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --time=5:00:00
#SBATCH --mem=90G
#SBATCH --mail-type=fail
#SBATCH --mail-user=aiavenak@iu.edu
#SBATCH --job-name=adni2bids
#SBATCH -o ADNI-subID-%j.out-%N
#SBATCH -e ADNI-subID-%j.err-%N

# * Environment
base="/N/project/cfn-rady/andrea-dev/ADNI"
ddir="${base}/LONI_download/sourcedata"
odir="${base}/rawdata"
cdir="/N/project/ADNI_rawdata/neuroimaging/conversions"
sdir="${base}/jobs"
ldir="${sdir}/logs"

# * Load conda as a module
module load conda

# * Initiate the virtual environment
conda activate /N/project/cfn-commons/neuroimaging_utils/python-envs/env_clinica
#export PATH="/N/project/statadni/20231213_Software/dcm2niix_v1.0.20240202:${PATH}"
module load dcm2niix/1.0.20230411

# * Run Clinica
clinica \
    convert adni-to-bids \
    -m T1 \
    -m FMRI \
    -m FLAIR \
    -m DWI \
    -m FMAP \
    --subjects_list "${sdir}/sub2convert.txt" \
    "${ddir}" \
    "${cdir}" \
    "${odir}" \
    | tee "${ldir}/adni_clinica_log.txt"

exit

