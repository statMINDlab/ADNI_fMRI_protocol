"""
ADNI Imaging + Matched-Clinical Swimlane Chart (calendar-date x-axis)
=====================================================================
Pipeline:
  1. Load imaging sessions (included_sessions_merged.csv)
  2. Load clinical tables (CDR, MMSE, ADAS, MoCA, DXSUM)
  3. Build a unified clinical visit table (one row per subject x date)
  4. Nearest-neighbour match each imaging session to the closest clinical
     visit within a configurable window (default 180 days).
     Clinical visits that are NOT the nearest match to some scan are DROPPED.
  5. Plot a swimlane chart on a calendar-date x-axis with:
       - Imaging visits as filled circles  (o)
       - Matched clinical visits as diamonds (<>)
       - A dotted connector showing the imaging<->clinical gap
       - Subjects sorted within dx group by date of first imaging visit

Note on undated scans: a small number of imaging sessions have no Scan_Date.
Because a date axis needs a real date, these are imputed from the subject's
nearest dated scan using the ADNI month offset (~30.44 days/month) and are
flagged as "date imputed" in the hover text.

Usage:
    python adni_swimlane_clinical.py \\
        --imaging  included_sessions_merged.csv \\
        --adas     ADAS_18Jul2026.csv \\
        --mmse     MMSE_18Jul2026.csv \\
        --cdr      CDR_18Jul2026.csv \\
        --dxsum    DXSUM_18Jul2026.csv \\
        --moca     MOCA_18Jul2026.csv \\
        --output   adni_swimlane_clinical.html

Requirements:
    pip install plotly pandas numpy
"""

import argparse
import numpy as np
import pandas as pd
import plotly.graph_objects as go

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DX_MAP   = {1.0: "CN", 2.0: "MCI", 3.0: "AD"}
DX_ORDER = ["CN", "MCI", "AD"]
COLORS   = {"CN": "#378ADD", "MCI": "#EF9F27", "AD": "#D85A30"}
NULL_COL = "rgba(136,136,136,0.75)"

IMG_SIZE    = 5      # imaging circle size
CLIN_SIZE   = 6      # clinical diamond size
LINE_W      = 1.2    # subject trajectory line
MATCH_W     = 1.0    # imaging <-> clinical connector
LINE_ALPHA  = 0.40
DOT_ALPHA   = 0.85
MATCH_ALPHA = 0.55

DAYS_PER_MONTH  = 30.44
MAX_MATCH_DAYS  = 180   # max gap to accept a clinical match

SCORE_COLS = ["MMSCORE", "CDGLOBAL", "CDRSB", "TOTSCORE", "TOTAL13",
              "MOCA", "clin_dx"]


# ---------------------------------------------------------------------------
# Step 1 - Load & prep imaging sessions
# ---------------------------------------------------------------------------

def load_imaging(path: str) -> pd.DataFrame:
    """Load imaging sessions and ensure every session has a usable date."""
    df = pd.read_csv(path, low_memory=False)
    df["RID"]       = df["Subject_ID"].str.extract(r"(\d+)$").astype(int)
    df["Scan_Date"] = pd.to_datetime(df["Scan_Date"], errors="coerce")
    df["img_month"] = df["ses"].str.extract(r"M(\d+)").astype(float)
    df["dx"]        = df["DIAGNOSIS"].map(DX_MAP)

    # --- impute missing scan dates -----------------------------------------
    # A date axis needs a real date, so for sessions lacking Scan_Date we
    # anchor on the subject's earliest dated scan and offset by the ADNI
    # month difference. Flagged so it is visible in the hover text.
    df["date_imputed"] = df["Scan_Date"].isna()

    dated = df.dropna(subset=["Scan_Date"]).sort_values("img_month")
    anchor_date  = dated.groupby("sub")["Scan_Date"].first()
    anchor_month = dated.groupby("sub")["img_month"].first()

    def _fill(row):
        if pd.notna(row["Scan_Date"]):
            return row["Scan_Date"]
        sub = row["sub"]
        if sub in anchor_date.index:
            delta = (row["img_month"] - anchor_month[sub]) * DAYS_PER_MONTH
            return anchor_date[sub] + pd.Timedelta(days=float(delta))
        return pd.NaT

    df["scan_date"] = df.apply(_fill, axis=1)

    n_drop = df["scan_date"].isna().sum()
    if n_drop:
        print(f"  WARNING: dropping {n_drop} session(s) with no derivable date")
        df = df.dropna(subset=["scan_date"])

    return df


# ---------------------------------------------------------------------------
# Step 2 - Load & unify clinical tables
# ---------------------------------------------------------------------------

def _prep_clin(df: pd.DataFrame, date_col: str, score_cols: list) -> pd.DataFrame:
    """Standardise one clinical table to RID + clin_date + scores."""
    df = df.copy()
    df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
    df = df.dropna(subset=["PTID", date_col])
    df["RID"] = df["PTID"].str.extract(r"(\d+)$").astype(int)
    keep = ["RID", "VISCODE2", date_col] + [c for c in score_cols if c in df.columns]
    return df[keep].rename(columns={date_col: "clin_date"})


def load_clinical(paths: dict) -> pd.DataFrame:
    """
    paths: dict with any of the keys adas / mmse / cdr / dxsum / moca
    Returns one row per (RID, clin_date) with scores merged across tables.
    """
    parts = []
    if "adas" in paths:
        parts.append(_prep_clin(pd.read_csv(paths["adas"], low_memory=False),
                                "VISDATE", ["TOTSCORE", "TOTAL13"]))
    if "mmse" in paths:
        parts.append(_prep_clin(pd.read_csv(paths["mmse"], low_memory=False),
                                "VISDATE", ["MMSCORE"]))
    if "cdr" in paths:
        parts.append(_prep_clin(pd.read_csv(paths["cdr"], low_memory=False),
                                "VISDATE", ["CDGLOBAL", "CDRSB"]))
    if "moca" in paths:
        parts.append(_prep_clin(pd.read_csv(paths["moca"], low_memory=False),
                                "VISDATE", ["MOCA"]))
    if "dxsum" in paths:
        parts.append(_prep_clin(pd.read_csv(paths["dxsum"], low_memory=False),
                                "EXAMDATE", ["DIAGNOSIS"]))

    if not parts:
        raise ValueError("No clinical files provided.")

    clin = pd.concat(parts, ignore_index=True)
    # Collapse duplicate RID+date rows, taking the first non-null per column
    clin = clin.groupby(["RID", "clin_date"]).first().reset_index()
    clin["clin_dx"] = clin["DIAGNOSIS"].map(DX_MAP) if "DIAGNOSIS" in clin else np.nan
    return clin


# ---------------------------------------------------------------------------
# Step 3 - Nearest-neighbour match imaging <-> clinical
# ---------------------------------------------------------------------------

def match_clinical(imaging: pd.DataFrame,
                   clinical: pd.DataFrame,
                   max_days: int = MAX_MATCH_DAYS) -> pd.DataFrame:
    """
    For every imaging session, attach the nearest clinical visit within
    max_days. Clinical visits that are not the nearest match to any scan
    are discarded (we only plot imaging sessions and their matches).

    Each clinical visit is used at most once: within a subject, imaging
    sessions are matched in ascending date order and a clinical visit that
    has already been claimed cannot be reused by a later scan.

    Returns one row per imaging session with columns:
        RID, sub, ses, img_month, scan_date, dx, date_imputed,
        clin_date, clin_days_diff, matched, + clinical score columns
    """
    img_rids = set(imaging["RID"].unique())
    clinical = clinical[clinical["RID"].isin(img_rids)].copy()

    rows = []
    for rid, img_grp in imaging.groupby("RID"):
        clin_grp = clinical[clinical["RID"] == rid]
        available = clin_grp.index.tolist()   # unclaimed clinical visits

        for _, irow in img_grp.sort_values("scan_date").iterrows():
            rec = {
                "RID":          rid,
                "sub":          irow["sub"],
                "ses":          irow["ses"],
                "img_month":    irow["img_month"],
                "scan_date":    irow["scan_date"],
                "dx":           irow["dx"],
                "date_imputed": bool(irow["date_imputed"]),
                "clin_date":      pd.NaT,
                "clin_days_diff": np.nan,
                "clin_days_signed": np.nan,
                "matched":        False,
            }
            for c in SCORE_COLS:
                rec[c] = np.nan

            if available:
                cand  = clin_grp.loc[available]
                diffs = (cand["clin_date"] - irow["scan_date"]).dt.days.abs()
                idx   = diffs.idxmin()
                if diffs[idx] <= max_days:
                    crow = clin_grp.loc[idx]
                    rec["clin_date"]      = crow["clin_date"]
                    rec["clin_days_diff"] = int(diffs[idx])
                    # signed: negative = clinical BEFORE scan, positive = after
                    rec["clin_days_signed"] = int(
                        (crow["clin_date"] - irow["scan_date"]).days)
                    rec["matched"]        = True
                    for c in SCORE_COLS:
                        rec[c] = crow.get(c, np.nan)
                    available.remove(idx)      # one clinical visit, one scan

            rows.append(rec)

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Step 4 - Subject ordering
# ---------------------------------------------------------------------------

def build_subjects(merged: pd.DataFrame) -> list:
    """Sort subjects by final dx group, then date of first imaging visit."""
    subjects = []
    for sub, grp in merged.groupby("sub"):
        grp       = grp.sort_values("scan_date")
        dxs       = grp["dx"].dropna().tolist()
        final_dx  = dxs[-1] if dxs else None
        subjects.append({
            "sub":        sub,
            "final_dx":   final_dx,
            "converter":  len(set(dxs)) > 1 if dxs else False,
            "first_date": grp["scan_date"].min(),
            "n_img":      len(grp),
            "n_matched":  int(grp["matched"].sum()),
        })

    order = {"CN": 0, "MCI": 1, "AD": 2, None: 3}
    subjects.sort(key=lambda s: (order[s["final_dx"]], s["first_date"], s["sub"]))
    return subjects


# ---------------------------------------------------------------------------
# Step 5 - Plot
# ---------------------------------------------------------------------------

def hex_to_rgba(hex_col: str, alpha: float) -> str:
    h = hex_col.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


def _score_lines(row) -> list:
    out = []
    if pd.notna(row.get("MMSCORE")):  out.append(f"MMSE: {row['MMSCORE']:.0f}")
    if pd.notna(row.get("CDGLOBAL")): out.append(f"CDR: {row['CDGLOBAL']:.1f}")
    if pd.notna(row.get("CDRSB")):    out.append(f"CDR-SB: {row['CDRSB']:.1f}")
    if pd.notna(row.get("TOTSCORE")): out.append(f"ADAS-Cog: {row['TOTSCORE']:.1f}")
    if pd.notna(row.get("MOCA")):     out.append(f"MoCA: {row['MOCA']:.0f}")
    return out


def hover_imaging(row, meta) -> str:
    short = row["sub"].replace("sub-ADNI", "")
    lines = [f"<b>{short}</b> &nbsp; {row['ses']}",
             f"Scan: {row['scan_date']:%Y-%m-%d}"
             + (" <i>(date imputed)</i>" if row["date_imputed"] else ""),
             f"Imaging dx: <b>{row['dx'] or '?'}</b>"]
    if row["matched"]:
        gap = int(row["clin_days_diff"])
        lines.append(f"Clinical: {row['clin_date']:%Y-%m-%d} "
                     + ("(same day)" if gap == 0 else f"({gap}d apart)"))
    else:
        lines.append("<i>no clinical visit within window</i>")
    if meta["converter"]:
        lines.append("<i>converter</i>")
    return "<br>".join(lines)


def hover_clinical(row, meta) -> str:
    short = row["sub"].replace("sub-ADNI", "")
    gap   = int(row["clin_days_diff"])
    lines = [f"<b>{short}</b> &nbsp; clinical visit",
             f"Date: {row['clin_date']:%Y-%m-%d}",
             f"Matched to {row['ses']} "
             + ("(same day)" if gap == 0 else f"({gap}d apart)")]
    lines += _score_lines(row)
    return "<br>".join(lines)


def build_gap_histogram(merged: pd.DataFrame,
                        subjects: list,
                        max_days: int = MAX_MATCH_DAYS,
                        binsize: int = 7) -> go.Figure:
    """
    Histogram of the imaging<->clinical time gap, one row per dx group.

    Uses the SIGNED gap (clinical minus scan date) so you can see whether the
    clinical visit tends to precede or follow the scan; 0 = same day.
    Subjects are assigned to a group by their final diagnosis, matching the
    grouping used in the swimlane chart.
    """
    from plotly.subplots import make_subplots

    group_of = {s["sub"]: s["final_dx"] for s in subjects}
    df = merged[merged["matched"]].copy()
    # Sessions whose scan date was imputed have a fabricated gap (it reflects
    # the month-offset estimate, not real scheduling), so exclude them here.
    n_imputed = int(df["date_imputed"].sum())
    df = df[~df["date_imputed"]]
    df["group"] = df["sub"].map(group_of)

    fig = make_subplots(
        rows=len(DX_ORDER), cols=1, shared_xaxes=True,
        vertical_spacing=0.07,
        subplot_titles=[f"{d}" for d in DX_ORDER])

    for i, d in enumerate(DX_ORDER, start=1):
        vals = df.loc[df["group"] == d, "clin_days_signed"].dropna()
        if not len(vals):
            continue

        fig.add_trace(go.Histogram(
            x=vals,
            xbins=dict(start=-max_days, end=max_days + binsize, size=binsize),
            marker=dict(color=hex_to_rgba(COLORS[d], 0.75),
                        line=dict(color=COLORS[d], width=0.5)),
            name=d, showlegend=False,
            hovertemplate="%{x} days<br>%{y} sessions<extra></extra>"),
            row=i, col=1)

        # zero reference line (clinical and scan on the same day)
        fig.add_vline(x=0, line=dict(color="rgba(80,80,80,0.5)",
                                     width=1, dash="dot"), row=i, col=1)

        med = vals.median()
        fig.add_vline(x=med, line=dict(color=COLORS[d], width=1.5), row=i, col=1)

        same_day = (vals == 0).mean() * 100
        wk       = (vals.abs() <= 7).mean() * 100
        # Plotly names the first subplot's axes 'x'/'y', not 'x1'/'y1'
        ax = "x" if i == 1 else f"x{i}"
        ay = "y" if i == 1 else f"y{i}"
        fig.add_annotation(
            x=0.99, xref=f"{ax} domain", y=0.92, yref=f"{ay} domain",
            xanchor="right", yanchor="top", showarrow=False,
            align="right", font=dict(size=15, color="#444"),
            text=(f"n={len(vals)} &nbsp; median {med:+.0f}d<br>"
                  f"{same_day:.0f}% same day &nbsp; {wk:.0f}% within 1wk"))

        fig.update_yaxes(title_text="sessions", row=i, col=1,
                         title_font=dict(size=17), tickfont=dict(size=15),
                         showgrid=True, gridcolor="rgba(180,180,180,0.25)")

    fig.update_xaxes(
        title_text="Clinical visit date minus scan date (days)   "
                   "← clinical first · scan first →",
        title_font=dict(size=18),
        row=len(DX_ORDER), col=1)
    fig.update_xaxes(range=[-max_days, max_days], zeroline=False,
                     tickfont=dict(size=15),
                     showgrid=True, gridcolor="rgba(180,180,180,0.25)")

    all_vals = df["clin_days_signed"].dropna()
    excl = (f" &nbsp;·&nbsp; {n_imputed} imputed-date scans excluded"
            if n_imputed else "")
    fig.update_layout(
        title=dict(text=(
            "Time between matched imaging and clinical visits, by group<br>"
            f"<sup>{len(all_vals)} matched sessions &nbsp;·&nbsp; "
            f"median |gap| {all_vals.abs().median():.0f}d &nbsp;·&nbsp; "
            f"{(all_vals.abs() <= 7).mean()*100:.0f}% within one week{excl}<br>"
            f"solid line = group median &nbsp;·&nbsp; dotted line = same day</sup>"),
            x=0.5, xanchor="center", y=0.985, yanchor="top",
            font=dict(size=21)),
        font=dict(size=17),
        plot_bgcolor="white", paper_bgcolor="white",
        height=800, bargap=0.05, showlegend=False,
        # The 3-line title is drawn inside the top margin, while the first
        # subplot title ("CN") is pinned to the top of the plot area. Without
        # a generous top margin the two collide.
        margin=dict(t=175, l=80, r=40, b=80))

    # nudge subplot titles (CN / MCI / AD) down slightly off their domain edge
    for ann in fig.layout.annotations[:len(DX_ORDER)]:
        ann.font.size = 17
        ann.yshift = 6
    return fig


def build_combined_figure(merged: pd.DataFrame,
                          subjects: list,
                          max_days: int = MAX_MATCH_DAYS,
                          binsize: int = 7) -> go.Figure:
    """
    Single figure with three panels:
        A (full width, top)   swimlane of imaging + matched clinical visits
        B (bottom left)       histogram of the imaging<->clinical gap
        C (bottom right)      per-group summary statistics table

    Panel B overlays the three dx groups rather than stacking them, since a
    half-width panel is too narrow for three legible stacked subplots.
    """
    from plotly.subplots import make_subplots

    # Panel geometry. Plotly derives subplot domains from these, so compute the
    # annotation anchors from the same numbers rather than eyeballing them:
    #   available height = 1 - vspace  ->  row2 spans (0, ROW2_H * avail)
    #   available width  = 1 - hspace  ->  col2 starts at COL1_W*avail + hspace
    # Panel B (histogram) is given the wider, shorter share; panel C is a
    # transposed (metric-per-row) table, so it stays narrow.
    ROW1_H, ROW2_H = 0.76, 0.24
    COL1_W, COL2_W = 0.70, 0.30
    VSPACE, HSPACE = 0.10, 0.07
    row2_top = ROW2_H * (1 - VSPACE)              # top edge of panels B and C
    col2_left = COL1_W * (1 - HSPACE) + HSPACE    # left edge of panel C

    n        = len(subjects)
    y_pos    = {s["sub"]: i for i, s in enumerate(subjects)}
    meta     = {s["sub"]: s for s in subjects}
    group_of = {s["sub"]: s["final_dx"] for s in subjects}

    fig = make_subplots(
        rows=2, cols=2,
        specs=[[{"type": "xy", "colspan": 2}, None],
               [{"type": "xy"}, {"type": "table"}]],
        row_heights=[ROW1_H, ROW2_H],
        column_widths=[COL1_W, COL2_W],
        vertical_spacing=VSPACE,
        horizontal_spacing=HSPACE,
    )

    # ── Panel A: swimlane ────────────────────────────────────────────────────
    line_x = {d: [] for d in DX_ORDER}; line_y = {d: [] for d in DX_ORDER}
    mat_x  = {d: [] for d in DX_ORDER}; mat_y  = {d: [] for d in DX_ORDER}
    img_x  = {d: [] for d in DX_ORDER}; img_y  = {d: [] for d in DX_ORDER}
    img_h  = {d: [] for d in DX_ORDER}
    cli_x  = {d: [] for d in DX_ORDER}; cli_y  = {d: [] for d in DX_ORDER}
    cli_h  = {d: [] for d in DX_ORDER}
    nx, ny, nh = [], [], []

    for s in subjects:
        sub, y = s["sub"], y_pos[s["sub"]]
        fdx    = s["final_dx"] or "CN"
        rows   = merged[merged["sub"] == sub].sort_values("scan_date")

        xs = rows["scan_date"].tolist()
        for j in range(len(xs) - 1):
            line_x[fdx] += [xs[j], xs[j + 1], None]
            line_y[fdx] += [y, y, None]

        for _, r in rows.iterrows():
            vdx = r["dx"]
            if vdx in COLORS:
                img_x[vdx].append(r["scan_date"]); img_y[vdx].append(y)
                img_h[vdx].append(hover_imaging(r, meta[sub]))
            else:
                nx.append(r["scan_date"]); ny.append(y)
                nh.append(hover_imaging(r, meta[sub]))
            if r["matched"]:
                cdx = r["clin_dx"] if r["clin_dx"] in COLORS else (
                      vdx if vdx in COLORS else "CN")
                cli_x[cdx].append(r["clin_date"]); cli_y[cdx].append(y)
                cli_h[cdx].append(hover_clinical(r, meta[sub]))
                if r["clin_days_diff"] > 0:
                    key = vdx if vdx in COLORS else fdx
                    mat_x[key] += [r["scan_date"], r["clin_date"], None]
                    mat_y[key] += [y, y, None]

    for d in DX_ORDER:
        if line_x[d]:
            fig.add_trace(go.Scatter(
                x=line_x[d], y=line_y[d], mode="lines",
                line=dict(color=hex_to_rgba(COLORS[d], LINE_ALPHA), width=LINE_W),
                showlegend=False, hoverinfo="skip",
                meta={"kind": "line", "dx": d}), row=1, col=1)
    for d in DX_ORDER:
        if mat_x[d]:
            fig.add_trace(go.Scatter(
                x=mat_x[d], y=mat_y[d], mode="lines",
                line=dict(color=hex_to_rgba(COLORS[d], MATCH_ALPHA),
                          width=MATCH_W, dash="dot"),
                showlegend=False, hoverinfo="skip",
                meta={"kind": "match", "dx": d}), row=1, col=1)
    for d in DX_ORDER:
        if img_x[d]:
            fig.add_trace(go.Scatter(
                x=img_x[d], y=img_y[d], mode="markers",
                marker=dict(symbol="circle", size=IMG_SIZE,
                            color=hex_to_rgba(COLORS[d], DOT_ALPHA),
                            line=dict(width=0)),
                name=f"{d} imaging", showlegend=True,
                hovertemplate="%{customdata}<extra></extra>", customdata=img_h[d],
                meta={"kind": "img", "dx": d}), row=1, col=1)
    for d in DX_ORDER:
        if cli_x[d]:
            fig.add_trace(go.Scatter(
                x=cli_x[d], y=cli_y[d], mode="markers",
                marker=dict(symbol="diamond", size=CLIN_SIZE,
                            color="rgba(0,0,0,0)",
                            line=dict(color=hex_to_rgba(COLORS[d], 0.9), width=1.3)),
                name=f"{d} clinical", showlegend=True,
                hovertemplate="%{customdata}<extra></extra>", customdata=cli_h[d],
                meta={"kind": "cli", "dx": d}), row=1, col=1)
    if nx:
        fig.add_trace(go.Scatter(
            x=nx, y=ny, mode="markers",
            marker=dict(symbol="circle", size=IMG_SIZE, color="rgba(0,0,0,0)",
                        line=dict(color=NULL_COL, width=1.2)),
            name="Unknown dx", showlegend=True,
            hovertemplate="%{customdata}<extra></extra>", customdata=nh,
            meta={"kind": "img", "dx": "NA"}), row=1, col=1)

    # ── Panel B: overlaid gap histogram ──────────────────────────────────────
    gap = merged[merged["matched"] & ~merged["date_imputed"]].copy()
    gap["group"] = gap["sub"].map(group_of)

    for d in DX_ORDER:
        vals = gap.loc[gap["group"] == d, "clin_days_signed"].dropna()
        if not len(vals):
            continue
        fig.add_trace(go.Histogram(
            x=vals,
            xbins=dict(start=-max_days, end=max_days + binsize, size=binsize),
            marker=dict(color=hex_to_rgba(COLORS[d], 0.55),
                        line=dict(color=COLORS[d], width=0.5)),
            name=d, showlegend=False,
            hovertemplate=f"{d}<br>%{{x}} days<br>%{{y}} sessions<extra></extra>",
            meta={"kind": "hist", "dx": d}), row=2, col=1)

    # ── Panel C: statistics table ────────────────────────────────────────────
    # Transposed relative to the obvious layout: one row per metric and one
    # column per group. That keeps the table narrow (5 slim columns instead of
    # 9 wide ones), leaving the width for the histogram in panel B.
    metric_names = ["Subjects", "Sessions", "Median", "p75", "p95",
                    "Max", "Same day", "≤1 wk"]
    groups = DX_ORDER + ["All"]

    def _stats(d: str) -> list:
        sub_g = gap if d == "All" else gap[gap["group"] == d]
        a = sub_g["clin_days_diff"]
        n_subj = (len(subjects) if d == "All"
                  else sum(1 for s in subjects if s["final_dx"] == d))
        if len(a) == 0:
            return [f"{n_subj}", "0"] + ["–"] * 6
        return [f"{n_subj}", f"{len(a)}", f"{a.median():.0f} d",
                f"{a.quantile(.75):.0f} d", f"{a.quantile(.95):.0f} d",
                f"{a.max():.0f} d", f"{a.eq(0).mean() * 100:.0f}%",
                f"{a.le(7).mean() * 100:.0f}%"]

    cols = [metric_names] + [_stats(d) for d in groups]

    # Tint each group column; the metric-name column stays neutral.
    col_fills = (["rgba(0,0,0,0.04)"]
                 + [hex_to_rgba(COLORS[d], 0.13) for d in DX_ORDER]
                 + ["rgba(0,0,0,0.05)"])
    hdr_fills = (["#f0f0f0"]
                 + [hex_to_rgba(COLORS[d], 0.28) for d in DX_ORDER]
                 + ["#e8e8e8"])
    hdr_fonts = ["#222"] + [COLORS[d] for d in DX_ORDER] + ["#333333"]

    fig.add_trace(go.Table(
        columnwidth=[88, 50, 50, 50, 50],
        header=dict(values=[f"<b>{h}</b>" for h in [""] + groups],
                    fill_color=hdr_fills, align="center",
                    font=dict(size=15, color=hdr_fonts), height=30),
        cells=dict(values=cols,
                   fill_color=col_fills,
                   align=["left"] + ["center"] * len(groups), height=26,
                   font=dict(size=14, color=["#222"] + ["#333"] * len(groups))),
    ), row=2, col=2)

    # ── shapes / annotations ─────────────────────────────────────────────────
    shapes, annotations = [], []
    prev = None
    for s in subjects:
        if s["final_dx"] != prev:
            yi = y_pos[s["sub"]]
            if prev is not None:
                shapes.append(dict(type="line", xref="x domain", yref="y",
                                   x0=0, x1=1, y0=yi - 0.5, y1=yi - 0.5,
                                   line=dict(color="rgba(100,100,100,0.35)",
                                             width=0.8, dash="dot")))
            annotations.append(dict(
                x=-0.008, xref="x domain", xanchor="right",
                y=yi, yref="y", yanchor="middle",
                text=f"<b>{s['final_dx']}</b>",
                font=dict(color=COLORS.get(s["final_dx"], "#888"), size=17),
                showarrow=False))
            prev = s["final_dx"]

    # same-day reference line in panel B
    shapes.append(dict(type="line", xref="x2", yref="y2 domain",
                       x0=0, x1=0, y0=0, y1=1,
                       line=dict(color="rgba(80,80,80,0.55)", width=1, dash="dot")))

    # panel letters, anchored to the true domain corners
    for letter, px, py in [("A", 0.0, 1.0),
                           ("B", 0.0, row2_top),
                           ("C", col2_left, row2_top)]:
        annotations.append(dict(
            x=px, y=py, xref="paper", yref="paper",
            xanchor="right", yanchor="bottom",
            text=f"<b>{letter}</b>", showarrow=False,
            font=dict(size=26, color="#222")))

    # panel sub-headings, left-aligned just right of each letter
    for text, px, py in [
            ("Imaging sessions and matched clinical visits", 0.012, 1.0),
            ("Imaging–clinical gap", 0.012, row2_top),
            ("Gap statistics by group", col2_left + 0.012, row2_top)]:
        annotations.append(dict(
            x=px, y=py, xref="paper", yref="paper",
            xanchor="left", yanchor="bottom", showarrow=False,
            text=text, font=dict(size=18, color="#444")))

    # ── layout ───────────────────────────────────────────────────────────────
    n_img     = len(merged)
    n_matched = int(merged["matched"].sum())
    n_imp     = int(merged["date_imputed"].sum())
    n_cn  = sum(1 for s in subjects if s["final_dx"] == "CN")
    n_mci = sum(1 for s in subjects if s["final_dx"] == "MCI")
    n_ad  = sum(1 for s in subjects if s["final_dx"] == "AD")
    y_pad = max(6.0, n * 0.012)

    fig.update_xaxes(title_text="Visit date", type="date",
                     title_font=dict(size=18), tickfont=dict(size=15),
                     showgrid=True, gridcolor="rgba(180,180,180,0.25)",
                     row=1, col=1)
    fig.update_yaxes(range=[-y_pad, n - 1 + y_pad], showticklabels=False,
                     showgrid=False, zeroline=False, row=1, col=1)

    fig.update_xaxes(title_text="Clinical date minus scan date (days)",
                     range=[-max_days, max_days],
                     title_font=dict(size=18), tickfont=dict(size=15),
                     showgrid=True, gridcolor="rgba(180,180,180,0.25)",
                     row=2, col=1)
    fig.update_yaxes(title_text="sessions",
                     title_font=dict(size=17), tickfont=dict(size=15),
                     showgrid=True, gridcolor="rgba(180,180,180,0.25)",
                     row=2, col=1)

    fig.update_layout(
        title=dict(text=(
            "ADNI imaging sessions and matched clinical visits<br>"
            f"<sup>{len(subjects)} subjects (CN={n_cn}, MCI={n_mci}, AD={n_ad})"
            f" &nbsp;·&nbsp; {n_img} imaging sessions &nbsp;·&nbsp; "
            f"{n_matched} matched within {max_days} d"
            + (f" &nbsp;·&nbsp; {n_imp} imputed scan dates excluded from B/C"
               if n_imp else "") + "</sup>"),
            x=0.5, xanchor="center", y=0.985, yanchor="top",
            font=dict(size=22)),
        font=dict(size=16),
        hoverlabel=dict(font_size=15),
        barmode="overlay",
        legend=dict(orientation="h", yanchor="bottom", y=1.045,
                    xanchor="center", x=0.5,
                    font=dict(size=15), itemsizing="constant"),
        plot_bgcolor="white", paper_bgcolor="white",
        height=max(900, int(n / 0.70) + 340),
        margin=dict(t=170, l=100, r=45, b=70),
        shapes=shapes, annotations=annotations,
        bargap=0.05,
    )
    return fig


def build_figure(merged: pd.DataFrame, subjects: list) -> go.Figure:
    fig = go.Figure()

    y_pos = {s["sub"]: i for i, s in enumerate(subjects)}
    meta  = {s["sub"]: s for s in subjects}
    n     = len(subjects)

    # group separators + labels
    shapes, annotations = [], []
    prev = None
    for s in subjects:
        if s["final_dx"] != prev:
            yi = y_pos[s["sub"]]
            if prev is not None:
                shapes.append(dict(type="line", xref="paper", yref="y",
                                   x0=0, x1=1, y0=yi - 0.5, y1=yi - 0.5,
                                   line=dict(color="rgba(100,100,100,0.35)",
                                             width=0.8, dash="dot")))
            annotations.append(dict(
                x=0, xref="paper", xanchor="right",
                y=yi, yref="y", yanchor="middle",
                text=f"<b>{s['final_dx']}</b>",
                font=dict(color=COLORS.get(s["final_dx"], "#888"), size=18),
                showarrow=False))
            prev = s["final_dx"]

    # accumulators
    line_x  = {d: [] for d in DX_ORDER}
    line_y  = {d: [] for d in DX_ORDER}
    match_x = {d: [] for d in DX_ORDER}
    match_y = {d: [] for d in DX_ORDER}
    img_x   = {d: [] for d in DX_ORDER}
    img_y   = {d: [] for d in DX_ORDER}
    img_h   = {d: [] for d in DX_ORDER}
    cli_x   = {d: [] for d in DX_ORDER}
    cli_y   = {d: [] for d in DX_ORDER}
    cli_h   = {d: [] for d in DX_ORDER}
    nx, ny, nh = [], [], []          # unknown-dx imaging

    for s in subjects:
        sub, y = s["sub"], y_pos[s["sub"]]
        fdx    = s["final_dx"] or "CN"
        rows   = merged[merged["sub"] == sub].sort_values("scan_date")

        xs = rows["scan_date"].tolist()
        for j in range(len(xs) - 1):
            line_x[fdx] += [xs[j], xs[j + 1], None]
            line_y[fdx] += [y, y, None]

        for _, r in rows.iterrows():
            vdx = r["dx"]
            if vdx in COLORS:
                img_x[vdx].append(r["scan_date"]); img_y[vdx].append(y)
                img_h[vdx].append(hover_imaging(r, meta[sub]))
            else:
                nx.append(r["scan_date"]); ny.append(y)
                nh.append(hover_imaging(r, meta[sub]))

            if r["matched"]:
                cdx = r["clin_dx"] if r["clin_dx"] in COLORS else (
                      vdx if vdx in COLORS else "CN")
                cli_x[cdx].append(r["clin_date"]); cli_y[cdx].append(y)
                cli_h[cdx].append(hover_clinical(r, meta[sub]))
                if r["clin_days_diff"] > 0:      # only draw a visible gap
                    key = vdx if vdx in COLORS else fdx
                    match_x[key] += [r["scan_date"], r["clin_date"], None]
                    match_y[key] += [y, y, None]

    # 1. subject trajectory lines
    for d in DX_ORDER:
        if line_x[d]:
            fig.add_trace(go.Scatter(
                x=line_x[d], y=line_y[d], mode="lines",
                line=dict(color=hex_to_rgba(COLORS[d], LINE_ALPHA), width=LINE_W),
                showlegend=False, hoverinfo="skip", name=f"{d} lines",
                meta={"kind": "line", "dx": d}))

    # 2. imaging <-> clinical gap connectors
    for d in DX_ORDER:
        if match_x[d]:
            fig.add_trace(go.Scatter(
                x=match_x[d], y=match_y[d], mode="lines",
                line=dict(color=hex_to_rgba(COLORS[d], MATCH_ALPHA),
                          width=MATCH_W, dash="dot"),
                showlegend=False, hoverinfo="skip", name=f"{d} gap",
                meta={"kind": "match", "dx": d}))

    # 3. imaging circles
    for d in DX_ORDER:
        if img_x[d]:
            fig.add_trace(go.Scatter(
                x=img_x[d], y=img_y[d], mode="markers",
                marker=dict(symbol="circle", size=IMG_SIZE,
                            color=hex_to_rgba(COLORS[d], DOT_ALPHA),
                            line=dict(width=0)),
                name=f"{d} imaging", legendgroup=f"img_{d}", showlegend=True,
                hovertemplate="%{customdata}<extra></extra>", customdata=img_h[d],
                meta={"kind": "img", "dx": d}))

    # 4. matched clinical diamonds
    for d in DX_ORDER:
        if cli_x[d]:
            fig.add_trace(go.Scatter(
                x=cli_x[d], y=cli_y[d], mode="markers",
                marker=dict(symbol="diamond", size=CLIN_SIZE,
                            color="rgba(0,0,0,0)",
                            line=dict(color=hex_to_rgba(COLORS[d], 0.9), width=1.3)),
                name=f"{d} clinical", legendgroup=f"cli_{d}", showlegend=True,
                hovertemplate="%{customdata}<extra></extra>", customdata=cli_h[d],
                meta={"kind": "cli", "dx": d}))

    # 5. unknown-dx imaging
    if nx:
        fig.add_trace(go.Scatter(
            x=nx, y=ny, mode="markers",
            marker=dict(symbol="circle", size=IMG_SIZE, color="rgba(0,0,0,0)",
                        line=dict(color=NULL_COL, width=1.2)),
            name="Unknown dx (imaging)", showlegend=True,
            hovertemplate="%{customdata}<extra></extra>", customdata=nh,
            meta={"kind": "img", "dx": "NA"}))

    # group filter buttons
    def vis(cn, mci, ad):
        out = []
        for t in fig.data:
            d = (t.meta or {}).get("dx", "")
            out.append(not ((d == "CN" and not cn) or
                            (d == "MCI" and not mci) or
                            (d == "AD" and not ad)))
        return out

    buttons = [
        dict(label="All", method="restyle", args=[{"visible": vis(True,  True,  True)}]),
        dict(label="CN",  method="restyle", args=[{"visible": vis(True,  False, False)}]),
        dict(label="MCI", method="restyle", args=[{"visible": vis(False, True,  False)}]),
        dict(label="AD",  method="restyle", args=[{"visible": vis(False, False, True)}]),
    ]

    n_img     = len(merged)
    n_matched = int(merged["matched"].sum())

    # Subjects occupy y = 0..n-1 and Plotly's y axis increases upward, so the
    # first group (CN) sits at the BOTTOM. Pad the range at both ends or the
    # outermost rows -- markers and the group label -- get clipped at the
    # figure edge. Pad is in data units; ~1 unit == 1 px at this height.
    fig_height = max(560, n + 220)
    y_pad      = max(6.0, n * 0.012)
    n_cn  = sum(1 for s in subjects if s["final_dx"] == "CN")
    n_mci = sum(1 for s in subjects if s["final_dx"] == "MCI")
    n_ad  = sum(1 for s in subjects if s["final_dx"] == "AD")
    gaps  = merged.loc[merged["matched"], "clin_days_diff"]
    med   = int(gaps.median()) if len(gaps) else 0

    fig.update_layout(
        title=dict(text=(
            f"ADNI imaging sessions with matched clinical visits<br>"
            f"<sup>{len(subjects)} subjects (CN={n_cn}, MCI={n_mci}, AD={n_ad}) &nbsp;·&nbsp; "
            f"{n_img} imaging sessions &nbsp;·&nbsp; {n_matched} matched to a clinical "
            f"visit (median gap {med}d)<br>"
            f"● imaging &nbsp; ◆ clinical &nbsp; ┈ gap between them</sup>"),
            x=0.5, xanchor="center", y=0.985, yanchor="top",
            font=dict(size=21)),
        font=dict(size=17),
        hoverlabel=dict(font_size=16),
        xaxis=dict(title="Visit date", type="date",
                   title_font=dict(size=18), tickfont=dict(size=16),
                   showgrid=True, gridcolor="rgba(180,180,180,0.25)",
                   gridwidth=0.5, zeroline=False),
        yaxis=dict(range=[-y_pad, n - 1 + y_pad], showticklabels=False,
                   showgrid=False, zeroline=False),
        legend=dict(title="Visit type / dx", itemsizing="constant",
                    tracegroupgap=6, font=dict(size=16),
                    title_font=dict(size=17)),
        plot_bgcolor="white", paper_bgcolor="white",
        height=fig_height,
        margin=dict(t=150, l=95, r=40, b=80),
        hovermode="closest",
        shapes=shapes, annotations=annotations,
        updatemenus=[dict(type="buttons", direction="right",
                          x=0.0, xanchor="left", y=1.09, yanchor="top",
                          buttons=buttons, showactive=True,
                          bgcolor="white", bordercolor="#cccccc",
                          font=dict(size=16))])
    return fig


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args():
    p = argparse.ArgumentParser(
        description="ADNI imaging + matched clinical swimlane (Plotly, date axis)")
    p.add_argument("--imaging", required=True, help="included_sessions_merged.csv")
    p.add_argument("--adas",  default=None)
    p.add_argument("--mmse",  default=None)
    p.add_argument("--cdr",   default=None)
    p.add_argument("--dxsum", default=None)
    p.add_argument("--moca",  default=None)
    p.add_argument("--output", default="adni_swimlane_clinical.html")
    p.add_argument("--hist-output", default="adni_gap_histogram.html",
                   help="Output HTML for the imaging-clinical gap histogram")
    p.add_argument("--combined-output", default="adni_combined_figure.html",
                   help="Output HTML for the combined A/B/C panel figure")
    p.add_argument("--binsize", type=int, default=7,
                   help="Histogram bin width in days (default 7)")
    p.add_argument("--max-days", type=int, default=MAX_MATCH_DAYS,
                   help=f"Max days gap for a clinical match (default {MAX_MATCH_DAYS})")
    p.add_argument("--save-merged", default=None,
                   help="Optional path to save the merged session table as CSV")
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    clin_paths = {k: getattr(args, k) for k in ("adas", "mmse", "cdr", "dxsum", "moca")
                  if getattr(args, k) is not None}

    print("Loading imaging sessions…")
    imaging = load_imaging(args.imaging)
    n_imp = int(imaging["date_imputed"].sum())
    print(f"  {len(imaging)} sessions, {imaging['RID'].nunique()} subjects"
          + (f" ({n_imp} scan dates imputed)" if n_imp else ""))

    print("Loading clinical tables…")
    clinical = load_clinical(clin_paths)
    clinical = clinical[clinical["RID"].isin(set(imaging["RID"]))]
    print(f"  {len(clinical)} clinical visits for these subjects")

    print(f"Matching (max gap = {args.max_days} days)…")
    merged = match_clinical(imaging, clinical, max_days=args.max_days)
    n_matched = int(merged["matched"].sum())
    gaps = merged.loc[merged["matched"], "clin_days_diff"]
    print(f"  {len(merged)} imaging sessions: {n_matched} matched, "
          f"{len(merged) - n_matched} unmatched")
    if len(gaps):
        print(f"  gap days — median {gaps.median():.0f}, "
              f"75th {gaps.quantile(.75):.0f}, max {gaps.max():.0f}")
    print(f"  {len(clinical) - n_matched} unmatched clinical visits dropped")

    if args.save_merged:
        merged.to_csv(args.save_merged, index=False)
        print(f"  Merged table saved to: {args.save_merged}")

    subjects = build_subjects(merged)
    print(f"Sorted {len(subjects)} subjects by dx group + first scan date")

    print("Building figure…")
    fig = build_figure(merged, subjects)
    fig.write_html(args.output, include_plotlyjs="cdn")
    print(f"Saved: {args.output}")

    print("Building gap histogram…")
    hfig = build_gap_histogram(merged, subjects,
                               max_days=args.max_days, binsize=args.binsize)
    hfig.write_html(args.hist_output, include_plotlyjs="cdn")
    print(f"Saved: {args.hist_output}")

    print("Building combined A/B/C figure…")
    cfig = build_combined_figure(merged, subjects,
                                 max_days=args.max_days, binsize=args.binsize)
    cfig.write_html(args.combined_output, include_plotlyjs="cdn")
    print(f"Saved: {args.combined_output}")

    # per-group gap summary
    group_of = {s["sub"]: s["final_dx"] for s in subjects}
    g = merged[merged["matched"] & ~merged["date_imputed"]].copy()
    g["group"] = g["sub"].map(group_of)
    print("\nGap between imaging and clinical visit (days), "
          "imputed-date scans excluded:")
    summary = (g.groupby("group")["clin_days_diff"]
                 .agg(n="size", median="median", p75=lambda s: s.quantile(.75),
                      p95=lambda s: s.quantile(.95), max="max"))
    summary["same_day_%"] = (g.assign(z=g["clin_days_diff"].eq(0))
                               .groupby("group")["z"].mean().mul(100).round(1))
    summary["within_1wk_%"] = (g.assign(w=g["clin_days_diff"].le(7))
                                 .groupby("group")["w"].mean().mul(100).round(1))
    print(summary.reindex(DX_ORDER).to_string())
