#!/bin/bash

path2slurmScripts=$1   # path to dir where SLURM scripts will be created
path2subjectList=$2   # path to text file with list of subject IDs

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

path2slurmTemplate="${3:-$script_dir}"

[[ -d "$path2slurmTemplate" || -f "$path2slurmTemplate" ]] \
  || { echo "Invalid path2slurmTemplate: $path2slurmTemplate" >&2; exit 1; }


#check that paths exist
if [ ! -d ${path2slurmScripts} ]; then
    echo "Error: Path to SLURM scripts directory ${path2slurmScripts} does not exist."
    exit 1
fi

if [ ! -f ${path2subjectList} ]; then
    echo "Error: Path to subject list file ${path2subjectList} does not exist."
    exit 1
fi  

# #check that modality is one of func, anat, dti
# if [ "${modality}" != "func" ] && [ "${modality}" != "anat" ] && [ "${modality}" != "dti" ]; then
#     echo "Error: Modality ${modality} is not recognized. Please use 'func', 'anat', or 'dti'."
#     exit 1
# fi

#cd ${path2slurmScripts}

for i in `cat ${path2subjectList}`
do
    echo ${i}
    echo ${i} > ${path2slurmScripts}/${i}.txt
    for m in func anat dti; do
        cp ${path2slurmTemplate}/adni_clinica_${m}.slurm ${path2slurmScripts}/${i}_adni_clinica_${m}.slurm
        sed -i "s|job-name=adni2bids|job-name=${i}_${m}|" ${path2slurmScripts}/${i}_adni_clinica_${m}.slurm
        sed -i "s|ADNI-subID|${i}|" ${path2slurmScripts}/${i}_adni_clinica_${m}.slurm
        sed -i "s|sub2convert|${i}|" ${path2slurmScripts}/${i}_adni_clinica_${m}.slurm
        sed -i "s|adni_clinica_log|${i}_${m}_log|" ${path2slurmScripts}/${i}_adni_clinica_${m}.slurm
    done

    # cp ${path2slurmTemplate}/adni_clinica.slurm ${path2slurmScripts}/${i}_adni_clinica.slurm
    # sed -i "s|job-name=adni2bids|job-name=adni2bids_${i}|" ${path2slurmScripts}/${i}_adni_clinica.slurm
    # sed -i "s|ADNI-subID|${i}|" ${path2slurmScripts}/${i}_adni_clinica.slurm
    # sed -i "s|sub2convert|${i}|" ${path2slurmScripts}/${i}_adni_clinica.slurm
    # sed -i "s|adni_clinica_log|adni_${i}_clinica_log|" ${path2slurmScripts}/${i}_adni_clinica.slurm
done
