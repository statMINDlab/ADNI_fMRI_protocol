import os
import re
import pandas as pd
from .base import PathStrategy

class DefaultFlatStrategy(PathStrategy):
    def __init__(self, base_dir, modality="fmri", bids_base_dir=None):
        self.base_dir = base_dir
        self.modality = modality
        self.bids_base_dir = bids_base_dir

    def load_anchor_df(self):
        all_dfs = []
        target_filename = f"{self.modality}_paths.tsv"

        for vdir in os.listdir(self.base_dir):
            full_path = os.path.join(self.base_dir, vdir)
            tsv_path = os.path.join(full_path, target_filename)
            if os.path.isfile(tsv_path):
                try:
                    df = pd.read_csv(tsv_path, sep="\t")
                    df["source_version"] = vdir
                    all_dfs.append(df)
                    print(f"Loaded: {tsv_path}")
                except Exception as e:
                    print(f"Error reading {tsv_path}: {e}")
        return pd.concat(all_dfs, ignore_index=True) if all_dfs else pd.DataFrame()

    def add_paths(self, df: pd.DataFrame) -> pd.DataFrame:
        nifti_paths, json_paths, nifti_exists, json_exists = [], [], [], []

        for row in df.itertuples():
            sub_id = row.Subject_ID.replace("_", "")
            vis = row.VISCODE.lower()
            match = re.search(r'm(\d+)', vis)

            if vis == "bl":
                session = "M000"
            elif match:
                session = f"M{int(match.group(1)):03d}"
            else:
                session = vis.upper()

            base = f"sub-ADNI{sub_id}_ses-{session}_task-rest_bold"
            nifti = os.path.join(self.bids_base_dir, f"sub-ADNI{sub_id}", f"ses-{session}", "func", f"{base}.nii.gz")
            json_ = nifti.replace(".nii.gz", ".json")

            nifti_paths.append(nifti)
            json_paths.append(json_)
            nifti_exists.append(os.path.exists(nifti))
            json_exists.append(os.path.exists(json_))

            if not os.path.exists(nifti):
                print(f"[WARNING] NIfTI not found: {nifti}")
            if not os.path.exists(json_):
                print(f"[WARNING] JSON not found: {json_}")

        df["NIfTI_path"] = nifti_paths
        df["JSON_path"] = json_paths
        df["NIfTI_exists"] = nifti_exists
        df["JSON_exists"] = json_exists
        return df