#!/bin/bash

#raw_dicom_dir="/N/project/cfn-rady/andrea-dev/ADNI/LONI_data/image_data/ADNI"
#raw_dicom_dir="/N/project/ADNI_rawdata/neuroimaging/sourcedata/original/participants"

raw_dicom_dir=$1  # Pass the raw DICOM directory as the first argument

if [ -z "$raw_dicom_dir" ]; then
  echo "Usage: $0 /path/to/raw_dicom_directory"
  exit 1
fi

if [ ! -d "$raw_dicom_dir" ]; then
  echo "Error: Directory $raw_dicom_dir does not exist."
  exit 1
fi

cd ${raw_dicom_dir}

echo "Subject,Description,Acq Date,ImageID" >> unzipped_dicom_dirs_inventory.csv

for sub in *; do
  [[ -d "$sub" ]] || continue
  echo "Processing subject: ${sub}"

  for series in "$sub"/*; do
    [[ -d "$series" ]] || continue
    series_name=$(basename "$series")
    clean_series=${series_name//,/--}  ## found Series Names with comas and that breaks the CSV files. 

    for date in "$series"/*; do
      [[ -d "$date" ]] || continue
      date_name=$(basename "$date")

      for imgID in "$date"/*; do
        [[ -d "$imgID" ]] || continue
        imgID_name=$(basename "$imgID")

        echo "${sub},${clean_series},${date_name},${imgID_name}" >> unzipped_dicom_dirs_inventory.csv
      done
    done
  done
done

echo "CSV file created: unzipped_dicom_dirs_inventory.csv"