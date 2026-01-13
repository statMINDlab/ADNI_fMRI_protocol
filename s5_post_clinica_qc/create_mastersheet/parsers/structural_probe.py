from pathlib import Path
import pandas as pd
import nibabel as nib
from tqdm import tqdm

class StructuralProbe:
    """
    StructuralProbe detects the presence of structural NIfTI images (e.g., T1w, FLAIR)
    and extracts key header metadata (dimensions, voxel sizes) using nibabel.
    
    It supports searching across multiple folders per session (e.g., anat, fmap, dwi),
    and returns a DataFrame with _exists flags, header fields, and file paths.
    
    Example usage:
        probe = StructuralProbe(modalities=["T1w", "FLAIR"], folders=["anat"])
        struct_df = probe.run(df)
        df = pd.concat([df, struct_df], axis=1)
    """

    HEADER_FIELDS = {
        "dim1": lambda hdr: int(hdr["dim"][1]),
        "dim2": lambda hdr: int(hdr["dim"][2]),
        "dim3": lambda hdr: int(hdr["dim"][3]),
        "pixdim1": lambda hdr: float(hdr["pixdim"][1]),
        "pixdim2": lambda hdr: float(hdr["pixdim"][2]),
        "pixdim3": lambda hdr: float(hdr["pixdim"][3]),
    }

    def __init__(self, modalities=["T1w", "FLAIR"], folders=["anat"]):
        """
        Initialize the probe.
        
        Args:
            modalities (list): List of modality suffixes to track (e.g., ["T1w", "FLAIR"]).
            folders (list): Subdirectories within each session to search (e.g., ["anat", "fmap"]).
        """
        self.modalities = modalities
        self.folders = folders

    def _extract_header_fields(self, nii_path, modality_prefix):
        """Safely load a NIfTI header and extract specified fields."""
        try:
            img = nib.load(nii_path)
            hdr = img.header
            return {
                f"{modality_prefix}_{field}": fn(hdr)
                for field, fn in self.HEADER_FIELDS.items()
            }
        except Exception as e:
            tqdm.write(f"[nibabel failed] {nii_path} — {e}")
            return {f"{modality_prefix}_{field}": None for field in self.HEADER_FIELDS}

    def run(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Run the structural probe on the provided DataFrame.
        
        Args:
            df (pd.DataFrame): Must include a column named 'NIfTI_path' to anchor each row.

        Returns:
            pd.DataFrame: A new DataFrame with columns:
                - {mod}_exists (True/False)
                - {mod}_dim{1–3}, {mod}_pixdim{1–3}
                - {mod}_path
        """
        all_rows = []
        for row in tqdm(df.itertuples(), total=len(df), desc="Structural probe: checking modality files"):
            nifti_path = getattr(row, "NIfTI_path")
            ses_dir = Path(nifti_path).parents[1]

            row_result = {}

            for mod in self.modalities:
                found_file = None

                for folder in self.folders:
                    search_dir = ses_dir / folder
                    if search_dir.exists():
                        file = next(search_dir.glob(f"*{mod}.nii.gz"), None)
                        if file:
                            found_file = file
                            break

                if found_file:
                    row_result[f"{mod}_path"] = str(found_file)
                    row_result[f"{mod}_exists"] = True
                    row_result.update(self._extract_header_fields(str(found_file), modality_prefix=mod))
                else:
                    row_result[f"{mod}_path"] = None
                    row_result[f"{mod}_exists"] = False
                    for field in self.HEADER_FIELDS:
                        row_result[f"{mod}_{field}"] = None

            all_rows.append(row_result)

        return pd.DataFrame(all_rows)