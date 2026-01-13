#!/bin/bash
path2slurmScripts=$1  # path to dir where SLURM scripts will be created
path2subjectList=$2  # path to text file with list of subject IDs
modality=$3  # imaging modality: anat, func, dti

#check that paths exist
if [ ! -d ${path2slurmScripts} ]; then
    echo "Error: Path to SLURM scripts directory ${path2slurmScripts} does not exist."
    exit 1
fi

if [ ! -f ${path2subjectList} ]; then
    echo "Error: Path to subject list file ${path2subjectList} does not exist."
    exit 1
fi 

#check that modality is one of func, anat, dti
if [ "${modality}" != "func" ] && [ "${modality}" != "anat" ] && [ "${modality}" != "dti" ]; then
    echo "Error: Modality ${modality} is not recognized. Please use 'func', 'anat', or 'dti'."
    exit 1
fi

for i in `cat ${path2subjectList}`; do
    echo ${i}
    if [ ! -f ${path2slurmScripts}/${i}_adni_clinica_${modality}.slurm ]; then
        echo "Error: ${path2slurmScripts}/${i}_adni_clinica_${modality}.slurm. NOT FOUND."
        continue
    fi
    sbatch ${path2slurmScripts}/${i}_adni_clinica_${modality}.slurm
done

