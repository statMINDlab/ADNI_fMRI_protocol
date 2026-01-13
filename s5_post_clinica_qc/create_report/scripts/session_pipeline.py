import pandas as pd
import heuristics as H  # Import all heuristics from separate file
import os

# Optional notebook-friendly display utilities. In non-notebook contexts (e.g.,
# CI or plain scripts) we fall back to simple print-based stubs so that calls to
# display(Markdown(...)) still work without introducing a hard dependency on
# IPython.
try:  # pragma: no cover - behavior is trivial and environment-dependent
    from IPython.display import display, Markdown
except Exception:  # noqa: BLE001 - broad to handle absence of IPython cleanly
    def display(obj):  # type: ignore[no-redef]
        """Fallback display: print Markdown or plain text to stdout."""
        print(obj)

    class Markdown(str):  # type: ignore[no-redef]
        """Lightweight stand-in so Markdown(text) behaves like a string."""

        pass

from plots import (
    render_scan_depth_plot,
    render_repetition_time_plot,
    render_coil_string_plot,
    render_percent_phase_fov_plot,
    render_remaining_parameters_plot,
    render_subject_session_histogram,
    render_multiband_vs_singleband_plot,
    render_total_duration_plot
)
from config import CONFIG
import plotly.express as px


class SessionFilterPipeline:
    """
    This class handles the multi-phase filtering of sessions using defined heuristics.
    Each phase runs a group of heuristics, and the results can be used to generate reports.
    """

    def __init__(self, csv_path):
        # === Load and store the input dataset ===
        self.df_original = pd.read_csv(csv_path)
        self.df_current = self.df_original.copy()
        self.initial_count = len(self.df_original)

        # === Tracking structures ===
        self.dropped_dfs = {}         # heuristic_name -> dropped DataFrame
        self.phase_checkpoints = {}   # phase_number -> df after that phase

        self._setup_phases()

    def _setup_phases(self):
        """
        Define which heuristics run in which phase.
        Each tuple is (function, name) for clarity and modularity.
        """
        self.phase_map = {
            0: [
                (H.filter_missing_data_adnidap, "filter_missing_data_adnidap"),
                (H.filter_missing_data, "filter_missing_data"),
                (H.filter_missing_t1w, "filter_missing_t1w")
                
            ],
            1: [  
                (H.filter_low_scan_depth, "filter_low_scan_depth"),
                (H.filter_invalid_repetition_time, "filter_invalid_repetition_time"),
                (H.filter_short_duration, "filter_short_duration")
            ],
            2: [
                (H.filter_low_percent_phase_fov, "filter_low_percent_phase_fov"),
                (H.filter_out_bad_coils, "filter_out_bad_coils")
            ]
        }

    def run(self, phase_limit=3, verbose=True):
        """
        Run the filtering pipeline up to the specified phase number.
        Tracks dropped rows and filtered DataFrames for reporting.
        """
        self.df_current = self.df_original.copy()
        self.dropped_dfs.clear()
        self.phase_checkpoints.clear()

        for phase, heuristics in self.phase_map.items():
            if phase > phase_limit:
                break
            if verbose:
                print(f"Phase {phase}:")
            for func, name in heuristics:
                mask = func(self.df_current, CONFIG)
                dropped = self.df_current[~mask].copy()
                kept = self.df_current[mask].copy()
                self.dropped_dfs[name] = dropped
                self.df_current = kept
                if verbose:
                    print(f"  {name}: Dropped {len(dropped)} rows, Remaining: {len(self.df_current)}")
            self.phase_checkpoints[phase] = self.df_current.copy()

    def get_phase_summary(self):
        """
        Return the drop statistics as a dictionary.
        Useful for report generation or Plotly visualizations.
        """
        total_dropped = sum(len(df) for df in self.dropped_dfs.values())
        return {
            "initial_count": self.initial_count,
            "final_kept": len(self.df_current),
            "total_dropped": total_dropped,
            "drop_details": {name: len(df) for name, df in self.dropped_dfs.items()}
        }
    
    def display_phase_summary(self):
        """
        Display a clean Markdown table summarizing heuristic drops,
        showing remaining rows *after each heuristic* and listing initial row count at the top.
        """
        name_map = {
            "filter_missing_data": "Missing Data",
            "filter_missing_data_adnidap": "BIDS",
            "filter_missing_t1w": "T1w Image Missing",
            "filter_invalid_repetition_time": "RepetitionTime (TR)",
            "filter_out_bad_coils": "CoilString",
            "filter_low_scan_depth": "ScanDepth (dim3×pixdim3)",
            "filter_low_percent_phase_fov": "PercentPhaseFOV",
            "filter_short_duration": "Scan Duration"
        }

        desc_map = {
            "RepetitionTime (TR)": "Sessions where TR falls outside [0.5–1.0] or [2.9–3.1] seconds.",
            "CoilString": "Sessions that use Q-BODY or BODY coils.",
            "ScanDepth (dim3×pixdim3)": "Scan Depth (dim₃ × pixdim₃) is outside the range [155, 180].",
            "PercentPhaseFOV": "A session with an unusually low value of ≤ 72.",
            "BIDS": "Sessions flagged due to known errors in Clinica BIDS conversion.",
            "Missing Data": "Sessions where required NIfTI or JSON files are missing after Clinica conversion.",
            "T1w Image Missing": "Session does not have a T1-weighted image.",
            "Scan Duration": "Sessions where total scan duration (TR × volumes) is less than 5 minutes."
        }

        rows = []
        last_phase = None
        running_total = self.initial_count
        initial_subjects = self.df_original["Subject_ID"].nunique()
        final_subjects = self.df_current["Subject_ID"].nunique()


        header = (
            f"#### Initial Session Count: {self.initial_count} ({initial_subjects} subjects)\n\n"
            "| Phase | Parameter | Criteria | Rows Dropped | Remaining Rows |\n"
            "|-------|-----------|----------|--------------|----------------|"
        )

        for phase, heuristics in self.phase_map.items():
            if phase not in self.phase_checkpoints:
                continue

            for _, code_name in heuristics:
                pretty_name = name_map.get(code_name, code_name)
                description = desc_map.get(pretty_name, "")
                dropped = len(self.dropped_dfs.get(code_name, []))
                running_total -= dropped

                phase_str = f"Phase {phase}" if phase != last_phase else ""
                last_phase = phase

                rows.append(
                    f"| {phase_str} | {pretty_name} | {description} | {dropped} | {running_total} |"
                )

        total_dropped = sum(len(df) for df in self.dropped_dfs.values())
        total_remaining = len(self.df_current)

        rows.append(
            f"| **TOTAL** | — | — | **{total_dropped}** | **{total_remaining}** |"
        )

        final_summary = (
            f"\n\n#### Final Session Count: {len(self.df_current)} ({final_subjects} subjects)"
        )

        markdown = header + "\n" + "\n".join(rows) + final_summary
        display(Markdown(markdown))

        render_subject_session_histogram(self.df_current)

    def render_phase0_summary(self):
        """
        Render Phase 0 summary with rich explanation and heuristic drop counts.
        Aligns with report's narrative and overview of applied filters.
        """
        d_bids = len(self.dropped_dfs.get("filter_missing_data_adnidap", []))
        d_missing = len(self.dropped_dfs.get("filter_missing_data", []))
        d_t1w = len(self.dropped_dfs.get("filter_missing_t1w", []))
        remaining = len(self.phase_checkpoints.get(0, []))

        md = f"""
Three checks were applied:

- **BIDS**: Sessions flagged due to known errors in Clinica BIDS conversion.
- **Missing Data**: Sessions where required `NIfTI` or `JSON` files are missing **after Clinica/BIDS conversion**, even if no error was reported.
- **T1w Image Missing**: Session does not have a T1-weighted image. 

These filters ensure that only sessions with the core imaging files required for analysis proceed to structural and quality-based checks in later phases.

### Dropped Summary

| Heuristic              | Sessions Dropped |
|------------------------|------------------|
| BIDS                   | {d_bids}         |
| Missing Data           | {d_missing}      |
| T1w Image Missing      | {d_t1w}          |
| Remaining After Phase 0| {remaining}      |
"""
        display(Markdown(md))


    def render_phase1_summary(self):
        """
        Render Phase 1 summary with explanations, drop counts, overlap analysis,
        and missingness faceted by manufacturer.
        """
        df_base = self.phase_checkpoints.get(0, self.df_original.copy()).copy()

        # Re-run masks independently
        mask_sd = H.filter_low_scan_depth(df_base, CONFIG)
        mask_tr = H.filter_invalid_repetition_time(df_base, CONFIG)
        mask_dur = H.filter_short_duration(df_base, CONFIG)

        dropped_sd = (~mask_sd).sum()
        dropped_tr = (~mask_tr).sum()
        dropped_dur = (~mask_dur).sum()

        # Overlap: dropped by all 3
        dropped_all = (~mask_sd & ~mask_tr & ~mask_dur).sum()

        # Total dropped: count of unique rows dropped by any of the 3
        mask_combined = mask_sd & mask_tr & mask_dur
        total_dropped = (~mask_combined).sum()

        remaining = len(self.phase_checkpoints.get(1, []))
        initial = len(df_base)

        scan_col = CONFIG["nifti_dim"]
        pix_col = CONFIG["nifti_pixdim"]
        tr_col = CONFIG["repetition_time"]

        manufacturers = ["Philips", "Siemens", "GE"]
        rows = []

        for m in manufacturers:
            sub = df_base[df_base["json_Manufacturer"] == m]
            missing_scan = sub[scan_col].isna().sum() + sub[pix_col].isna().sum()
            missing_tr = sub[tr_col].isna().sum()
            rows.append(f"| {m} | {missing_scan} | {missing_tr} |")

        md = f"""
Three heuristics were evaluated:

- **ScanDepth (dim₃ × pixdim₃)**: Sessions with dim₃ × pixdim₃ < 155 were flagged.
- **RepetitionTime (TR)**: Sessions with TR outside [0.5–1.0] or [2.9–3.1] seconds were flagged.
- **Scan Duration**: Sessions where `TR × volumes` is < 300 seconds (i.e., under 5 minutes).

These thresholds are chosen to ensure structural and temporal resolution integrity.  
- ScanDepth values above 155 typically reflect sufficient anatomical coverage.  
- TR values within [0.5–1.0] or [2.9–3.1] seconds are considered standard for multiband and single-band protocols.  
- Short scans (<5 minutes) may indicate incomplete acquisitions.

The bullet points below summarize missing values by manufacturer, while the table highlights how many sessions were dropped by each heuristic.

### Missing Field Counts by Manufacturer
""" + "\n".join(
    [f"- **{m}**: {rows[i].split('|')[2].strip()} missing ScanDepth, {rows[i].split('|')[3].strip()} missing TR"
    for i, m in enumerate(manufacturers)]
) + f"""

### Dropped Summary

| Heuristic         | Sessions Dropped |
|------------------|------------------|
| ScanDepth         | {dropped_sd}     |
| RepetitionTime    | {dropped_tr}     |
| Scan Duration     | {dropped_dur}    |
| Dropped by All 3  | {dropped_all}    |
| Remaining After Phase 1 | {remaining} |

### Overlap Analysis

→ **Total dropped in Phase 1 = ({dropped_sd} + {dropped_tr} + {dropped_dur}) − {dropped_all} = {dropped_sd + dropped_tr + dropped_dur} − {dropped_all} = {total_dropped} sessions**  
→ **Remaining = {initial} − {total_dropped} = {remaining} sessions**
    """
        display(Markdown(md))

    def render_phase2_summary(self):
        """
        Render Phase 2 summary with explanations, drop counts, and missingness
        for PercentPhaseFOV and CoilString, faceted by manufacturer.
        """
        df_base = self.phase_checkpoints.get(1, self.df_original.copy()).copy()

        # Re-run both masks independently on original data
        mask_fov = H.filter_low_percent_phase_fov(df_base, CONFIG)
        mask_coil = H.filter_out_bad_coils(df_base, CONFIG)

        dropped_fov = (~mask_fov).sum()
        dropped_coil = (~mask_coil).sum()
        dropped_both = (~mask_fov & ~mask_coil).sum()
        total_dropped = dropped_fov + dropped_coil - dropped_both
        remaining = len(self.phase_checkpoints.get(2, []))

        fov_col = CONFIG["percent_phase_fov"]
        coil_col = CONFIG["coil_string"]

        manufacturers = ["Philips", "Siemens", "GE"]
        rows = []

        for m in manufacturers:
            sub = df_base[df_base["json_Manufacturer"] == m]
            missing_fov = sub[fov_col].isna().sum()
            missing_coil = sub[coil_col].isna().sum()
            rows.append(f"| {m} | {missing_fov} | {missing_coil} |")
            

        md = f"""
Two heuristics were evaluated:

- **PercentPhaseFOV**: Sessions with json_PercentPhaseFOV ≤ 72 were flagged.
- **CoilString**: Sessions that used Q-BODY or BODY coils were flagged for exclusion.

These filters were applied to ensure imaging consistency. An unusually low PercentPhaseFOV (e.g., 72%) may indicate problematic field coverage. Additionally, coils labeled Q-BODY or BODY are not used for brain imaging.

The bullet points below summarize missing values by manufacturer, while the table highlights how many sessions were dropped by each heuristic.

### Missing Field Counts by Manufacturer
""" + "\n".join(
    [f"- **{m}**: {rows[i].split('|')[2].strip()} missing PercentPhaseFOV, {rows[i].split('|')[3].strip()} missing CoilString"
     for i, m in enumerate(manufacturers)]
) + f"""

### Dropped Summary

| Heuristic                | Sessions Dropped |
|--------------------------|------------------|
| PercentPhaseFOV          | {dropped_fov}    |
| CoilString               | {dropped_coil}   |
| Dropped by Both          | {dropped_both}   |
| Remaining After Phase 2  | {remaining}      |

### Overlap Analysis

→ **Total dropped in Phase 2 = ({dropped_fov} + {dropped_coil}) − {dropped_both} = {total_dropped} sessions**  
→ **Remaining = {len(df_base)} − {total_dropped} = {remaining} sessions**
"""

        display(Markdown(md))

    def render_final_missingness_by_manufacturer(self):
        """
        Display a Markdown table of missing value counts for key parameters,
        faceted by manufacturer (Philips, Siemens, GE), including ScanDepth.
        """
        df = self.df_current.copy()
        manufacturers = ["Philips", "Siemens", "GE"]

        # --- Columns to inspect ---
        categorical_columns = [
            CONFIG["repetition_time"],
            CONFIG["magnetic_field_strength"],
            CONFIG["manufacturer_model"],
            CONFIG["institution_name"],
            CONFIG["mr_acquisition_type"],
            CONFIG["slice_thickness"],
            CONFIG["spacing_between_slices"],
            CONFIG["echo_time"],
            CONFIG["flip_angle"],
            CONFIG["percent_phase_fov"],
            CONFIG["percent_sampling"],
            CONFIG["echo_train_length"],
            CONFIG["acquisition_matrix_pe"],
            CONFIG["phase_encoding_direction"],
            CONFIG["coil_string"],
            CONFIG["mr_acquisition_freq_encoding"],
            CONFIG["phase_encoding_axis"]
        ]

        # Add ScanDepth (dim3 * pixdim3) as a derived field
        df["ScanDepth"] = df[CONFIG["nifti_dim"]].apply(lambda x: eval(x)[3] if pd.notna(x) else None) * \
                        df[CONFIG["nifti_pixdim"]].apply(lambda x: eval(x)[3] if pd.notna(x) else None)

        categorical_columns.append("ScanDepth")

        rows = []
        for col in categorical_columns:
            label = col.replace("json_", "").replace("dicom_", "")
            row = [label]
            for m in manufacturers:
                sub = df[df["json_Manufacturer"] == m]
                missing = sub[col].isna().sum()
                row.append(str(missing))
            rows.append(row)

        # Build Markdown
        header = "| Parameter | Philips | Siemens | GE |\n|-----------|---------|---------|----|"
        body = "\n".join([f"| {r[0]} | {r[1]} | {r[2]} | {r[3]} |" for r in rows])

        md = f"### Final Missing Data by Parameter (Faceted by Manufacturer)\n\n{header}\n{body}"
        display(Markdown(md))

    def render_phase1_scan_plot(self, produce_html=False, html_path="scan_depth_plot_phase1.html"):
        """
        Render scan depth scatter plot using the filtered dataframe after Phase 0.
        """
        df = self.phase_checkpoints.get(0)
        if df is None:
            print("Phase 0 data not available. Run the pipeline first.")
            return
        render_scan_depth_plot(df, produce_html=produce_html, html_path=html_path)
    
    def render_phase1_tr_plot(self, produce_html=False, html_path="repetition_time_by_site.html"):
        df = self.phase_checkpoints.get(0)
        if df is None:
            print("Phase 0 data not available. Run the pipeline first.")
            return
        from plots import render_repetition_time_plot
        render_repetition_time_plot(df, produce_html=produce_html, html_path=html_path)

    def render_phase1_duration_plot(self, produce_html=False, html_path="total_duration_plot_phase1.html"):
        """
        Render scan duration plot (TR × volumes) using the filtered dataframe after Phase 0.
        """
        df = self.phase_checkpoints.get(0)
        if df is None:
            print("Phase 0 data not available. Run the pipeline first.")
            return
        render_total_duration_plot(df, produce_html=produce_html, html_path=html_path)

    def render_phase2_coil_plot(self, produce_html=False, html_path="coil_string_by_site.html"):
        df = self.phase_checkpoints.get(1)
        if df is None:
            print("Phase 1 data not available. Run the pipeline first.")
            return
        render_coil_string_plot(df, produce_html=produce_html, html_path=html_path)

    def render_phase2_fov_plot(self, produce_html=False, html_path="percent_phase_fov_by_site.html"):
        df = self.phase_checkpoints.get(1)
        if df is None:
            print("Phase 1 data not available. Run the pipeline first.")
            return
        render_percent_phase_fov_plot(df, produce_html=produce_html, html_path=html_path)

    def render_final_filtered_plots(self, output_dir="final_plots", produce_html=False):
        """
        Render the main plots using the filtered dataframe after all heuristics have been applied.
        These plots reflect the cleaned data that passed structural and quality checks.
        """
        df_final = self.df_current.copy()
        os.makedirs(output_dir, exist_ok=True)

        # Render Section 6 header in notebook
        display(Markdown(
            "The following plots were generated from the filtered dataset after all heuristic checks "
            "were completed. They reflect the final, cleaned cohort and capture key acquisition parameters "
            "across sites and manufacturers."
        ))

        render_scan_depth_plot(df_final, produce_html=produce_html, html_path=f"{output_dir}/scan_depth.html")
        render_repetition_time_plot(df_final, produce_html=produce_html, html_path=f"{output_dir}/tr_plot.html")
        render_total_duration_plot(df_final, produce_html=produce_html, html_path=f"{output_dir}/total_duration.html")
        render_coil_string_plot(df_final, produce_html=produce_html, html_path=f"{output_dir}/coil_string.html")
        render_percent_phase_fov_plot(df_final, produce_html=produce_html, html_path=f"{output_dir}/percent_phase_fov.html")

    def render_all_final_plots(self, output_dir="final_plots", produce_html=False):
        """
        Render all key plots using the filtered dataframe after all phases are complete.
        Plots are saved to disk if `produce_html=True`.
        """
        df_final = self.df_current.copy()
        os.makedirs(output_dir, exist_ok=True)

        render_multiband_vs_singleband_plot(df_final, produce_html=produce_html, html_path=f"{output_dir}/mb_vs_sb_timeline.html")
        render_remaining_parameters_plot(df_final, produce_html=produce_html, html_dir=output_dir)
        
def run_heuristics(csv_path, phase_limit=3, display_markdown=True):
    """
    Run the full pipeline up to a phase and optionally display Markdown summary.
    Returns the SessionFilterPipeline object for further inspection or export.
    """
    pipeline = SessionFilterPipeline(csv_path)
    pipeline.run(phase_limit=phase_limit, verbose=False)  
    if display_markdown:
        pipeline.display_phase_summary()
    return pipeline