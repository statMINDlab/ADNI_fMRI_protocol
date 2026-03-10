import nibabel as nib
import json
import os
from tqdm import tqdm

class NiftiParser:
    def __init__(self, nifti_path, json_path):
        self.nifti_path = nifti_path
        self.json_path = json_path
        self.metadata = {}

    def parse(self):
        if os.path.exists(self.nifti_path):
            try:
                nii = nib.load(self.nifti_path)
                header = dict(nii.header)
                for k, v in header.items():
                    if isinstance(v, bytes):
                        header[k] = v.decode("utf-8", errors="ignore")
                    elif hasattr(v, 'tolist'):
                        header[k] = v.tolist()
                self.metadata.update({f"nifti_{k}": v for k, v in header.items()})
            except Exception as e:
                tqdm.write(f"[Error reading NIfTI] {self.nifti_path} — {e}")
        else:
            tqdm.write(f"[Missing NIfTI] {self.nifti_path}")
        
        if os.path.exists(self.json_path):
            try:
                with open(self.json_path, 'r') as f:
                    json_meta = json.load(f)
                    self.metadata.update({f"json_{k}": v for k, v in json_meta.items()})
            except Exception as e:
                tqdm.write(f"[Error reading JSON] {self.json_path} — {e}")
        else:
            tqdm.write(f"[Missing JSON] {self.json_path}")

        return self.metadata