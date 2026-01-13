import os
import pydicom
import warnings
from tqdm import tqdm

# Suppress pydicom UserWarnings about invalid VR UI values
warnings.filterwarnings("ignore", category=UserWarning, module="pydicom")

class DICOMMetadata:
    def __init__(self, dicom_dir):
        self.dir = dicom_dir
        self.path = self._find_dicom_file(dicom_dir)
        self.metadata = {}
        self._load()

    def _find_dicom_file(self, dicom_dir):
        for file in os.listdir(dicom_dir):
            full_path = os.path.join(dicom_dir, file)
            if os.path.isfile(full_path):
                return full_path
        raise FileNotFoundError(f"No DICOM file found in directory: {dicom_dir}")

    def _load(self):
        try:
            ds = pydicom.dcmread(self.path, stop_before_pixels=True)
            self.metadata = {
                elem.keyword: elem.value
                for elem in ds
                if elem.keyword and elem.value is not None
            }
        except Exception as e:
            tqdm.write(f"Failed to read DICOM at {self.path}: {e}")
            self.metadata = {}

    def get(self, key, default=None):
        return self.metadata.get(key, default)

    def to_dict(self):
        return {"dicom_" + k: v for k, v in self.metadata.items()}