#%%
from parsers.anchors import AnchorTable
from parsers.dicom_parser import DICOMMetadata
from parsers.nifti_parser import NiftiParser
from parsers.structural_probe import StructuralProbe
from config.dicom_fields import dcm_keep_fields
from parsers.path_strategies.default_flat import DefaultFlatStrategy
from parsers.path_strategies.per_subject import PerSubjectStrategy
from tqdm import tqdm
import os
from pathlib import Path

import pandas as pd
import sys

# Ensure repo root (so we can import utils.config_tools) is on sys.path
REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from utils.config_tools import load_config, get_value  # type: ignore

#%%

def main(config_path: str | None = None):
    #%% Load anchors that allow us to join dfs from NIFTI and DICOM header data

    # Use subject_dirs + PerSubjectStrategy if your BIDS data is split across multiple root folders
    #subject_dirs = [
    #    "/N/project/statadni/20231219_ADNI/sourcedata_dev_1",
    #    "/N/project/statadni/20231219_ADNI/sourcedata_dev_2",
    #    "/N/project/statadni/20231219_ADNI/sourcedata_dev_3",
    #    "/N/project/statadni/20231219_ADNI/sourcedata_dev_4"
    #]   
    #strategy = PerSubjectStrategy(subject_dirs, modality="fmri")

    # Use DefaultFlatStrategy if your BIDS data is all under a single root folder.
    # Paths are now read from config/config_adni.yaml via utils.config_tools:
    #   - paths.clinica_conversion_info_dir : folder containing Clinica conversion_info
    #   - paths.clinica_bids_dir            : BIDS root folder
    cfg = load_config(config_path)
    conv_info_dir = get_value(cfg, "paths.clinica_conversion_info_dir")
    bids_base_dir = get_value(cfg, "paths.clinica_bids_dir")

    strategy = DefaultFlatStrategy(
        base_dir=conv_info_dir,
        modality="fmri",
        bids_base_dir=bids_base_dir,
    )

    anchors = AnchorTable(strategy=strategy)
    anchor_df = anchors.get_df()
    
    #%% Load DICOM header data into a dataframe using paths from our Anchors
    dicom_df = None
    if anchors.hash_has_changed() or not os.path.exists("data/anchor_plus_dicom.csv"):
        dicom_objects = []
        for row in tqdm(anchor_df.itertuples(), total=len(anchor_df), desc="Parsing DICOMs"):
            try:
                dicom_path = row.Path
                dicom_meta = DICOMMetadata(dicom_path)
                meta_dict = dicom_meta.to_dict()
                trimmed = {k: meta_dict[k] for k in dcm_keep_fields if k in meta_dict}
                dicom_objects.append(trimmed)
            except Exception as e:
                tqdm.write(f"Failed to parse DICOM (this row will not contain DICOM information) - {e}")

        dicom_df = pd.DataFrame(dicom_objects)
        merged_df = pd.concat([anchor_df.reset_index(drop=True), dicom_df.reset_index(drop=True)], axis=1)
        merged_df.to_csv("data/anchor_plus_dicom.csv", index=False)
        print("Merged DICOM with anchor and saved.")
    else:
        print("Anchor table unchanged. Skipping DICOM parsing.")
        merged_df = pd.read_csv("data/anchor_plus_dicom.csv")

    #%% Load NIfTI + JSONs header data into a dataframe using paths from our Anchors and combine.
    nifti_objects = []
    for row in tqdm(merged_df.itertuples(), total=len(merged_df), desc="Parsing NIfTI + JSON"):
        try:
            parser = NiftiParser(row.NIfTI_path, row.JSON_path)
            parsed_meta = parser.parse()
            nifti_objects.append(parsed_meta)
        except Exception as e:
            tqdm.write(f"Failed to parse NIfTI/JSON for (this row will not contain NIFTI/JSON information) {row.Subject_ID}, {row.VISCODE} — {e}")
            nifti_objects.append({})  # keep row count aligned

    nifti_df = pd.DataFrame(nifti_objects)
    final_df = pd.concat([merged_df.reset_index(drop=True), nifti_df.reset_index(drop=True)], axis=1)
    # In the future add hash checking to avoid re-parsing
    # final_df.to_csv("data/anchor_plus_dicom_nifti.csv", index=False)
    # print(f"Final merged DataFrame saved with {final_df.shape[0]} rows and {final_df.shape[1]} columns.")

    #%% Feature Addition: Extract structural MRI metrics via StructuralProbe
    probe = StructuralProbe(modalities=["T1w", "FLAIR"], folders=["anat"]) # Adjust modalities as needed, e.g., remove "FLAIR" if only using T1w
    struct_df = probe.run(final_df)
    final_df = pd.concat([final_df.reset_index(drop=True), struct_df.reset_index(drop=True)], axis=1)
    final_df.to_csv("data/anchor_plus_dicom_nifti_struct.csv", index=False)
    print(f"Structural probe complete. Final dataset saved with {final_df.shape[0]} rows and {final_df.shape[1]} columns.")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description=(
            "Build anchor + DICOM + NIfTI+JSON + structural feature table "
            "for post-Clinica QC, using paths from config/config_adni.yaml."
        )
    )
    parser.add_argument(
        "--config",
        dest="config_path",
        default=None,
        help=(
            "Optional path to a YAML config file. If omitted, uses $ADNI_CONFIG "
            "or config/config_adni.yaml."
        ),
    )
    args = parser.parse_args()

    main(config_path=args.config_path)
