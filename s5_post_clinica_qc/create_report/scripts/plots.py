import plotly.express as px
import ast
import pandas as pd
from config import CONFIG
import os

# Optional notebook-only dependencies
try:  # pragma: no cover - trivial import guard
    from IPython.display import Markdown, display
except ImportError:  # When running in plain Python/CI environments
    def Markdown(text):  # type: ignore[override]
        """Fallback Markdown shim when IPython is unavailable."""
        return text

    def display(*_args, **_kwargs):  # type: ignore[override]
        """No-op display so scripts can run without IPython."""
        return None

# Should add a config file for the paramters to consolidate everything.

def render_scan_depth_plot(df, produce_html=False, html_path="scan_depth_scatter_by_manufacturer_adni.html"):
    df = df.copy()

    # Parse stringified lists
    df["nifti_dim"] = df["nifti_dim"].apply(lambda x: ast.literal_eval(x) if pd.notna(x) else [None]*8)
    df["nifti_pixdim"] = df["nifti_pixdim"].apply(lambda x: ast.literal_eval(x) if pd.notna(x) else [None]*8)

    df["dim3"] = df["nifti_dim"].apply(lambda x: x[3] if len(x) > 3 else None)
    df["pixdim3"] = df["nifti_pixdim"].apply(lambda x: x[3] if len(x) > 3 else None)
    df["ScanDepth"] = df["dim3"] * df["pixdim3"]
    df["Site"] = df["Subject_ID"].astype(str).str[:3]

    df = df[df["json_Manufacturer"].isin(["Philips", "Siemens", "GE"])]

    fig = px.scatter(
        df,
        x="Site",
        y="ScanDepth",
        color="Site",
        facet_col="json_Manufacturer",
        title="Scan Depth Across Sites, Faceted by Manufacturer",
        labels={"ScanDepth": "Scan Depth", "Site": "Site"}
    )

    fig.update_layout(height=600, width=1200, showlegend=True)

    for i in range(3):
        xref = f"x{i+1} domain" if i > 0 else "x domain"
        yref = f"y{i+1}" if i > 0 else "y"
        fig.add_shape(
            type="rect", x0=0, x1=1, y0=155, y1=180,
            xref=xref, yref=yref,
            fillcolor="green", opacity=0.2,
            layer="below", line_width=0,
        )

    fig.show()

    if produce_html:
        fig.write_html(html_path)
        print(f"Plot saved to: {html_path}")

def render_repetition_time_plot(df, produce_html=False, html_path="repetition_time_by_site.html"):
    df = df.copy()
    df["Site"] = df["Subject_ID"].astype(str).str[:3]

    # Only keep rows with known TR and valid manufacturers
    df = df[df["json_Manufacturer"].isin(["Philips", "Siemens", "GE"])]
    df = df[df["json_RepetitionTime"].notna()]

    # Identify multiband vs singleband
    df["ScanType"] = df["json_RepetitionTime"].apply(lambda tr: "MB" if tr < 1 else "SB")

    fig = px.scatter(
        df,
        x="Site",
        y="json_RepetitionTime",
        color="Site",
        symbol="ScanType",
        symbol_map={"SB": "circle-open", "MB": "circle"},
        facet_col="json_Manufacturer",
        title="Repetition Time (TR) Across Sites, Faceted by Manufacturer",
        labels={
            "json_RepetitionTime": "Repetition Time (s)",
            "Site": "Site",
            "ScanType": "Scan Type"
        },
        hover_data=["Subject_ID", "Image_ID"]
    )

    fig.update_layout(height=600, width=1200, showlegend=True)

    # Add green zones for accepted TR ranges
    for i in range(3):  # one for each facet (Philips, Siemens, GE)
        xref = f"x{i+1} domain" if i > 0 else "x domain"
        yref = f"y{i+1}" if i > 0 else "y"

        # Zone 1: 0.5 – 1.0 s
        fig.add_shape(
            type="rect", x0=0, x1=1, y0=0.5, y1=1.0,
            xref=xref, yref=yref,
            fillcolor="green", opacity=0.2, layer="below", line_width=0
        )

        # Zone 2: 2.9 – 3.1 s
        fig.add_shape(
            type="rect", x0=0, x1=1, y0=2.9, y1=3.1,
            xref=xref, yref=yref,
            fillcolor="green", opacity=0.2, layer="below", line_width=0
        )

    fig.show()

    if produce_html:
        fig.write_html(html_path)
        print(f"Plot saved to: {html_path}")

def render_coil_string_plot(df, produce_html=False, html_path="coil_string_by_site.html"):
    df = df.copy()
    df["Site"] = df["Subject_ID"].astype(str).str[:3]
    df = df[df["json_Manufacturer"].isin(["Philips", "Siemens", "GE"])]
    df = df[df["json_CoilString"].notna()]

    fig = px.scatter(
        df,
        x="Site",
        y="json_CoilString",
        color="json_CoilString",
        facet_col="json_Manufacturer",
        title="CoilString Values Across Sites, Faceted by Manufacturer",
        labels={"json_CoilString": "Coil String", "Site": "Site"}
    )

    fig.update_layout(height=600, width=1200, showlegend=True)
    fig.show()

    if produce_html:
        fig.write_html(html_path)
        print(f"Plot saved to: {html_path}")


def render_percent_phase_fov_plot(df, produce_html=False, html_path="percent_phase_fov_by_site.html"):
    df = df.copy()
    df["Site"] = df["Subject_ID"].astype(str).str[:3]
    df = df[df["json_Manufacturer"].isin(["Philips", "Siemens", "GE"])]
    df = df[df["json_PercentPhaseFOV"].notna()]

    fig = px.scatter(
        df,
        x="Site",
        y="json_PercentPhaseFOV",
        color="Site",
        facet_col="json_Manufacturer",
        title="PercentPhaseFOV Across Sites, Faceted by Manufacturer",
        labels={"json_PercentPhaseFOV": "PercentPhaseFOV", "Site": "Site"}
    )

    fig.update_layout(height=600, width=1200, showlegend=True)
    fig.show()

    if produce_html:
        fig.write_html(html_path)
        print(f"Plot saved to: {html_path}")

def render_remaining_parameters_plot(df, produce_html=False, html_dir="plots_remaining/"):
    """
    Render faceted plots for all remaining parameters, one per HTML file.

    Parameters:
        df (pd.DataFrame): The input DataFrame.
        produce_html (bool): Whether to save plots as HTML files.
        html_dir (str): Directory to save HTML files in.
    """
    df = df.copy()
    df["Site"] = df["Subject_ID"].astype(str).str[:3]
    df = df[df["json_Manufacturer"].isin(["Philips", "Siemens", "GE"])]

    # categorical_columns = [
    #     "json_MagneticFieldStrength", "json_ManufacturersModelName",
    #     "json_InstitutionName", "json_MRAcquisitionType", "json_SliceThickness", "json_SpacingBetweenSlices",
    #     "json_EchoTime", "json_FlipAngle", "json_PercentSampling", "json_EchoTrainLength",
    #     "json_AcquisitionMatrixPE", "json_PhaseEncodingDirection",
    #     "dicom_MRAcquisitionFrequencyEncodingSteps", "json_PhaseEncodingAxis"
    # ]

    categorical_columns = [
    # Section A: Supplemental Plots Provided for Context Only
    "json_ManufacturersModelName",
    "json_InstitutionName",
    "json_EchoTrainLength",
    "json_AcquisitionMatrixPE",
    "json_PhaseEncodingDirection",
    "json_PhaseEncodingAxis",

    # Section B: Parameters Considered for Heuristic Use but Not Flagged
    "json_MagneticFieldStrength",
    "json_MRAcquisitionType",
    "json_SliceThickness",
    "json_SpacingBetweenSlices",
    "json_FlipAngle",
    "json_PercentSampling",
    "dicom_MRAcquisitionFrequencyEncodingSteps",
    "json_EchoTime"
]

    df[categorical_columns] = df[categorical_columns].fillna("Not Provided")
    site_order = sorted(df["Site"].unique(), key=lambda x: int(x))

    if produce_html:
        os.makedirs(html_dir, exist_ok=True)

    for col in categorical_columns:
        if col == "json_Manufacturer":
            continue  # no need to plot manufacturer vs manufacturer

        if col == "json_MagneticFieldStrength":
            display(Markdown("---\n\n## B. Parameters Considered for Heuristic Use but Not Flagged\n"))

        col_clean = col.split("_", 1)[-1] if "_" in col else col
        df_plot = df[df[col] != "Not Provided"].copy()
        df_plot["ColorLabel"] = df_plot[col].astype(str)

        fig = px.scatter(
            df_plot,
            x="Site",
            y=col,
            color="ColorLabel",
            facet_col="json_Manufacturer",
            title=f"{col_clean} Values Across Sites (Faceted by Manufacturer)",
            labels={
                "Site": "Site",
                col: col_clean,
                "ColorLabel": col_clean
            },
            category_orders={"Site": site_order}
        )

        fig.update_layout(
            height=600,
            width=1200,
            title_font_size=16,
            showlegend=True
        )

        if produce_html:
            html_path = os.path.join(html_dir, f"{col_clean}_faceted_by_manufacturer.html")
            fig.write_html(html_path)
            print(f"Saved: {html_path}")
        else:
            fig.show()

def render_multiband_vs_singleband_plot(df, produce_html=False, html_path="multiband_vs_singleband_plot.html"):
    """
    Plot multiband (MB) vs single-band (SB) session distribution over time across sites.
    MB sessions appear underneath SB for visual clarity.

    Parameters:
        df (pd.DataFrame): The input DataFrame.
        produce_html (bool): Whether to save the figure as HTML.
        html_path (str): Output path for HTML if `produce_html=True`.
    """
    df = df.copy()
    df["Site"] = df["Subject_ID"].astype(str).str[:3]
    df[CONFIG["SeriesDate"]] = pd.to_datetime(df[CONFIG["SeriesDate"]], format="%Y%m%d", errors="coerce")
    df["ScanType"] = df[CONFIG["repetition_time"]].apply(lambda tr: "MB" if tr < 1 else "SB")

    symbol_map = {"MB": "circle", "SB": "x"}
    hover_data = {
        "ScanType": True,
        CONFIG["SeriesDate"]: True,
        "Site": True,
        CONFIG["repetition_time"]: True,
        CONFIG["PTID"]: True,
        "VISCODE": True,
    }

    # Plot MB sessions first (underneath)
    fig = px.scatter(
        df[df["ScanType"] == "MB"],
        x=CONFIG["SeriesDate"],
        y="Site",
        symbol="ScanType",
        title="Multiband vs Single-band Sessions Over Time",
        labels={CONFIG["SeriesDate"]: "Scan Date", "Site": "Site"},
        category_orders={"Site": sorted(df["Site"].unique())},
        symbol_map=symbol_map,
        hover_data=hover_data,
    )

    # Overlay SB sessions on top
    fig.add_trace(
        px.scatter(
            df[df["ScanType"] == "SB"],
            x=CONFIG["SeriesDate"],
            y="Site",
            symbol="ScanType",
            hover_data=hover_data,
        ).update_traces(marker=dict(size=6, color="black", symbol="x")).data[0]
    )

    # Emphasize MB marker size
    fig.update_traces(marker=dict(size=10), selector=dict(name="MB"))

    # Optional: dynamic height for many sites
    # num_sites = df["Site"].nunique()
    # fig_height = max(600, num_sites * 25)
    # fig.update_layout(height=fig_height)

    fig.update_layout( # Default if you don't want to use the dynamic height above
        height=600,
        width=1200
    )

    fig.show()

    if produce_html:
        fig.write_html(html_path)
        print(f"Plot saved as '{html_path}' with SB on top and correct hover data")


def render_subject_session_histogram(df, output_html=None):
    """
    Render a histogram showing how many subjects had N sessions.

    Parameters:
    - df: pandas DataFrame with 'Subject_ID' column.
    - output_html: Optional path to save the interactive HTML plot.
    """
    df = df.copy()
    df["Subject"] = df["Subject_ID"].str.extract(r"S_(\d+)$")[0]

    # Count how many sessions each subject had (frequency)
    histogram_df = (
        df["Subject"]
        .value_counts()
        .rename_axis("Subject")
        .reset_index(name="Sessions")
    )

    fig = px.histogram(
        histogram_df,
        x="Sessions",
        # nbins=20,
        title="Histogram of Sessions per Subject",
        labels={"Sessions": "# of Sessions", "count": "# of Subjects"}
    )

    fig.update_layout(
        bargap=0.1,
        width=550,
        # height=300,
        xaxis_dtick=1,
        margin=dict(l=60, r=40, t=60, b=60),
        xaxis_title="# of Sessions",
        yaxis_title="# of Subjects"
    )

    if output_html:
        fig.write_html(output_html)
    else:
        fig.show()


def render_subject_session_barplot(df, output_html=None):
    """
    Render a bar chart of number of sessions per subject.

    Parameters:
    - df: pandas DataFrame with a 'Subject_ID' column.
    - output_html: Optional path to save the interactive HTML plot.
    """
    df = df.copy()
    df["Short_Subject_ID"] = df["Subject_ID"].str.extract(r"S_(\d+)$")[0]

    subject_session_counts = (
        df["Short_Subject_ID"]
        .value_counts()
        .sort_index()
        .rename_axis("Subject")
        .reset_index(name="Number of Sessions")
    )

    subject_session_counts["Subject"] = subject_session_counts["Subject"].astype(str)

    fig = px.bar(
        subject_session_counts,
        x="Subject",
        y="Number of Sessions",
        title="Remaining Sessions per Subject (After Filtering)",
        labels={"Subject": "Subject ID", "Number of Sessions": "# of Sessions"},
    )

    fig.update_layout(
        width=3000,
        height=500,
        xaxis_title="Subject ID",
        yaxis_title="# of Sessions",
        xaxis_tickangle=-45,
        bargap=0.1,
        margin=dict(l=60, r=40, t=60, b=60)
    )

    if output_html:
        fig.write_html(output_html)
    else:
        fig.show()


def render_total_duration_plot(df, produce_html=False, html_path="total_duration_plot.html"):
    """
    Render total scan duration = TR × # volumes, faceted by manufacturer.
    
    Parameters:
        df (pd.DataFrame): Input DataFrame.
        produce_html (bool): Whether to save plot as HTML.
        html_path (str): Output HTML file path if produce_html is True.
    """
    df = df.copy()

    # Parse nifti_dim safely
    df["nifti_dim"] = df["nifti_dim"].apply(lambda x: ast.literal_eval(x) if isinstance(x, str) else x)
    df["n_volumes"] = df["nifti_dim"].apply(lambda dim: dim[4] if isinstance(dim, list) and len(dim) > 4 else None)

    # Use TR from config
    df["TR"] = df[CONFIG["repetition_time"]]
    df["Duration_sec"] = df["TR"] * df["n_volumes"]
    df["Site"] = df["Subject_ID"].astype(str).str[:3]

    df = df[df["json_Manufacturer"].isin(["Philips", "Siemens", "GE"])]
    df = df[df["Duration_sec"].notna()]

    hover_data = {
        "Subject_ID": True,
        "TR": True,
        "n_volumes": True,
        "Duration_sec": True,
        "Site": True,
        "nifti_dim": True,
        "nifti_pixdim": True,
    }

    fig = px.scatter(
        df,
        x="Site",
        y="Duration_sec",
        color="Site",
        facet_col="json_Manufacturer",
        title="Total Duration (TR × #Volumes) Across Sites",
        labels={"Duration_sec": "Total Scan Duration (seconds)", "Site": "Site"},
        hover_data=hover_data
    )

    fig.update_layout(height=600, width=1200, showlegend=True)

    # Add green bands: 7 min (±10s) and 10 min (±10s)
    green_bands = [(410, 430), (590, 610)]
    for i in range(3):  # for each manufacturer facet
        xref = f"x{i+1} domain" if i > 0 else "x domain"
        yref = f"y{i+1}" if i > 0 else "y"
        for y0, y1 in green_bands:
            fig.add_shape(
                type="rect",
                x0=0, x1=1,
                y0=y0, y1=y1,
                xref=xref, yref=yref,
                fillcolor="green",
                opacity=0.2,
                layer="below",
                line_width=0,
            )

    fig.show()

    if produce_html:
        fig.write_html(html_path)
        print(f"Plot saved to: {html_path}")