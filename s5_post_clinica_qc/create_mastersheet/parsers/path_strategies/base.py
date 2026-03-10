from abc import ABC, abstractmethod
import pandas as pd

class PathStrategy(ABC):
    @abstractmethod
    def load_anchor_df(self) -> pd.DataFrame:
        """Return a fully assembled DataFrame from conversion_info folder(s)."""
        pass

    @abstractmethod
    def add_paths(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add NIfTI/JSON paths and existence checks to the given df."""
        pass