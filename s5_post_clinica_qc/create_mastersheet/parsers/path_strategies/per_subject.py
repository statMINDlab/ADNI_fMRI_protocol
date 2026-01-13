import os
import re
import pandas as pd
from .base import PathStrategy

class PerSubjectStrategy(PathStrategy):
    def __init__(self, subject_dirs, modality="fmri"):
        """
        subject_dirs: List of directories like sourcedata1/, sourcedata2/, etc.
        modality: "fmri", "t1", etc.
        """
        self.subject_dirs = subject_dirs
        self.modality = modality

    def load_anchor_df(self):
        all_dfs = []
        for base_dir in self.subject_dirs:
            for subject_id in os.listdir(base_dir):
                subject_path = os.path.join(base_dir, subject_id)
                if not os.path.isdir(subject_path):
                    print(f"[WARNING]: Invalid path: {subject_path} ")
                    continue  # skip files

                conv_info_path = os.path.join(subject_path, "conversion_info")
                if not os.path.isdir(conv_info_path):
                    print("[WARNING]: No conversion_info clnica file.")
                    continue  # skip if no conversion_info

                # Look inside versioned subdirs (like v0, v1, ...)
                for version_dir in os.listdir(conv_info_path):
                    version_path = os.path.join(conv_info_path, version_dir)
                    if not os.path.isdir(version_path): # Skip over non-folders
                        continue

                    tsv_path = os.path.join(version_path, f"{self.modality}_paths.tsv")
                    # print(f"[DEBUG] Checking: {tsv_path}")

                    if os.path.isfile(tsv_path):
                        try:
                            df = pd.read_csv(tsv_path, sep="\t")
                            if df.empty or df.isna().all().all():  print(f"[DEBUG] Empty or all-NA DataFrame: {tsv_path}")
                            df["source_subject_path"] = subject_path
                            df["source_version"] = version_dir
                            all_dfs.append(df)
                            print(f"[✓] Loaded: {tsv_path}")
                        except Exception as e:
                            print(f"[ERROR] Failed to read {tsv_path}: {e}")
        # return pd.concat(all_dfs, ignore_index=True) if all_dfs else pd.DataFrame()
        valid_dfs = [df for df in all_dfs if not df.empty and not df.isna().all().all()] # Filter out empties
        return pd.concat(valid_dfs, ignore_index=True) if valid_dfs else pd.DataFrame()

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
            # subject_dir = row.source_subject
            subject_path = row.source_subject_path
            # nifti = os.path.join(subject_dir, f"sub-ADNI{sub_id}", f"ses-{session}", "func", f"{base}.nii.gz")
            nifti = os.path.join(subject_path, f"sub-ADNI{sub_id}", f"ses-{session}", "func", f"{base}.nii.gz")
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