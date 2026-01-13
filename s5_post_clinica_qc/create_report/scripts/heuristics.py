import ast

# Individual Heuristic Functions

def filter_invalid_repetition_time(df, config):
    """
    Return rows where json_RepetitionTime is either in [0.5, 1.0] or [2.9, 3.1].
    """
    col = config["repetition_time"]
    return ((df[col] >= 0.5) & (df[col] <= 1.0)) | ((df[col] >= 2.9) & (df[col] <= 3.1))

def filter_out_bad_coils(df, config):
    """
    Exclude rows where json_CoilString is one of the bad coils.
    """
    bad_coils = ['Q-Body', 'BODY']
    col = config["coil_string"]
    return ~df[col].isin(bad_coils)

def filter_low_scan_depth(df, config):
    """
    Keep rows where 180 => nifti_dim[3] * nifti_pixdim[3] >= 155.
    Handles malformed strings and NaNs gracefully.
    """
    dim_col = config["nifti_dim"]
    pixdim_col = config["nifti_pixdim"]
    def is_valid(row):
        try:
            dim = ast.literal_eval(row[dim_col])
            pixdim = ast.literal_eval(row[pixdim_col])
            depth = dim[3] * pixdim[3]
            return 155 <= depth <= 180
        except Exception:
            print(f"Malformed data in row: {row.name}, skipping.")
            return False
    return df.apply(is_valid, axis=1)

def filter_missing_data(df, config):
    """
    Filter out rows where either NIfTI or JSON does not exist.
    Must be marked 'TRUE' (case-insensitive) in both fields.
    """
    nifti_col = config["nifti_exists"]
    json_col = config["json_exists"]
    nifti_mask = df[nifti_col].astype(str).str.strip().str.upper() == "TRUE"
    json_mask = df[json_col].astype(str).str.strip().str.upper() == "TRUE"
    return nifti_mask & json_mask

def filter_missing_data_adnidap(df, config):
    """
    Filter out rows identified as bad by ADNIDap QC.
    This is a static example and should eventually be replaced with real QC logic.
    """
    bad_image_ids = [1341794, 401073, 1636121, 1259845]
    return ~df["Image_ID"].isin(bad_image_ids)

def filter_low_percent_phase_fov(df, config):
    """
    Remove rows where json_PercentPhaseFOV is less than or equal to 72.
    """
    col = config["percent_phase_fov"]
    # return (df[col] >= 72) & (df[col] <= 130)
    return df[col] > 72

def filter_missing_t1w(df, config):
    """
    Filter out rows where the T1-weighted image does not exist.
    Requires the column to be 'TRUE' (case-insensitive).
    """
    col = config["T1w_exists"]
    return df[col].astype(str).str.strip().str.upper() == "TRUE"

def filter_short_duration(df, config):
    """
    Keep rows where total scan duration (TR × n_volumes) is at least 300 seconds.
    Optional upper bound: exclude sessions longer than 900 seconds (15 minutes).
    """
    df = df.copy()
    df["nifti_dim"] = df["nifti_dim"].apply(lambda x: ast.literal_eval(x) if isinstance(x, str) else x)
    df["n_volumes"] = df["nifti_dim"].apply(lambda dim: dim[4] if isinstance(dim, list) and len(dim) > 4 else None)
    df["TR"] = df[config["repetition_time"]]
    df["Duration_sec"] = df["TR"] * df["n_volumes"]

    # return (df["Duration_sec"] >= 300) & (df["Duration_sec"] <= 900)  # Use this for  5–15 min range
    return df["Duration_sec"] >= 300