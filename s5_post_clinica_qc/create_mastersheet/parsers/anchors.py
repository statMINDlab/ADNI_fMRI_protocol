import os
import pandas as pd
import re
import hashlib
from parsers.path_strategies.base import PathStrategy
from parsers.path_strategies.default_flat import DefaultFlatStrategy

class AnchorTable:
    def __init__(self, strategy, cache_path="data/anchor_df.csv", hash_path="data/anchor_hash.txt"):
        self.path_strategy = strategy
        self.cache_path = cache_path
        self.hash_path = hash_path
        self.df = self._load_and_process()

    def _calculate_hash(self, df):
        content = df.to_csv(index=False).encode('utf-8')
        return hashlib.md5(content).hexdigest()

    def _load_and_process(self):
        print("Loading anchor table...")
        df = self.path_strategy.load_anchor_df()
        if df.empty: raise Exception("No Clnica *.tsv found for original DICOM paths.")

        # Sort and deduplicate
        df["version_num"] = df["source_version"].str.extract(r"v(\d+)").astype(int)
        df = df[df["Path"].notnull() & (df["Path"].str.strip() != "")]
        df = df.sort_values("version_num", ascending=False)
        df = df.drop_duplicates(subset=["Subject_ID", "VISCODE"], keep="first").copy()
        df.drop(columns=["version_num"], inplace=True)

        df = self.path_strategy.add_paths(df)

        os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
        df.to_csv(self.cache_path, index=False)
        with open(self.hash_path, "w") as f:
            f.write(self._calculate_hash(df))

        print(f"Anchor table saved to {self.cache_path}")
        return df

    def get_df(self):
        return self.df

    def get_hash(self):
        return self._calculate_hash(self.df)

    def hash_has_changed(self):
        if not os.path.exists(self.hash_path):
            return True
        with open(self.hash_path, "r") as f:
            return f.read().strip() != self.get_hash()