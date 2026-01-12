#!/bin/bash

basepath=/N/project/statadni
BIDS_indiv=${basepath}/BIDS_individual/ # path to Clinica BIDS output directory (where indidividual subject folders are located)

mkdir -p ${basepath}/BIDS_all
mkdir -p ${basepath}/BIDS_all/conversion_info
mkdir -p ${basepath}/BIDS_all/conversion_info/v0

for i in `cat ${basepath}/s4_clinica/adni_subs.txt`
do
    echo "Merging subject ${i} BIDS folder"
    if [[ -e ${BIDS_indiv}/${i} ]]; then
        cp -r ${BIDS_indiv}/${i} ${basepath}/BIDS_all/sub-${i}
        if [[ ! -e ${BIDS_indiv}/${i}/conversion_info/v0/fmri_paths.tsv ]]; then
            cat ${BIDS_indiv}/${i}/conversion_info/v0/fmri_paths.tsv >> ${basepath}/BIDS_all/conversion_info/v0/fmri_paths.tsv
        fi
        if [[ ! -e ${BIDS_indiv}/${i}/conversion_info/v0/t1w_paths.tsv ]]; then
            cat ${BIDS_indiv}/${i}/conversion_info/v0/t1w_paths.tsv >> ${basepath}/BIDS_all/conversion_info/v0/t1w_paths.tsv
        fi
        if [[ ! -e ${BIDS_indiv}/${i}/conversion_info/v0/flair_paths.tsv ]]; then
            cat ${BIDS_indiv}/${i}/conversion_info/v0/flair_paths.tsv >> ${basepath}/BIDS_all/conversion_info/v0/flair_paths.tsv
        fi
        if [[ ! -e ${BIDS_indiv}/${i}/conversion_info/v0/participants.tsv ]]; then
            cat ${BIDS_indiv}/${i}/conversion_info/v0/participants.tsv >> ${basepath}/BIDS_all/conversion_info/v0/participants.tsv
        fi
    else
        echo "Subject ${i} BIDS folder not found, skipping."
    fi
done

