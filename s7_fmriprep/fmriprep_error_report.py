#!/usr/bin/env python3
"""
fMRIPrep Failure Classifier with BOLD-Existence and SyN/PhaseEncodingDirection Checks
-------------------------------------------------------------------------------------
Scans Slurm stdout/stderr logs and fMRIPrep crashfiles to classify common failure modes,
and adds explicit categories for:
  - Missing/invalid FreeSurfer license
  - BIDS / TemplateFlow / ANTs / resource issues
  - No BOLD found (according to the log)
  - BOLD existing in other sessions but excluded by filters
  - Missing PhaseEncodingDirection for fieldmap-less (SyN) SDC
  - BOLD existence on disk (subject/session) via the BIDS tree
"""

import argparse, re, csv
from pathlib import Path
from typing import List, Tuple, Optional, Dict

# ---- Known patterns (triples: regex, category, note) ----
PATTERNS = [
    (re.compile(r"argument --session-label: expected at least one argument", re.I),
     "CLI: missing --session-label value",
     "Passed --session-label with no value. Remove it or supply a session."),

    (re.compile(r"command not found.*--skip[-_]?bids[-_]?validation", re.I),
     "CLI: flag typo / line continuation broke",
     "Use --skip-bids-validation and ensure line continuations '\\\\' are correct."),

    (re.compile(r"RuntimeError: a valid license file is required for FreeSurfer", re.I),
     "FreeSurfer: license missing/invalid",
     "Bind a valid FS license to /opt/freesurfer/license.txt."),

    (re.compile(r"No such file or directory: '.*/opt/freesurfer/license\\.txt'", re.I),
     "FreeSurfer: license path not bound",
     "Bind FS license path (-B) and use --fs-license-file /opt/freesurfer/license.txt."),

    (re.compile(r"MemoryError|Cannot allocate memory|killed process.*out of memory|killed\\s+.*mem", re.I),
     "Resources: Out of memory",
     "Increase --mem/--cpus-per-task; consider dropping --cifti-output."),

    (re.compile(r"TIME LIMIT", re.I),
     "Resources: Walltime exceeded",
     "Increase --time; consider splitting sessions or disabling heavy options."),

    (re.compile(r"Permission denied", re.I),
     "I/O: Permission denied",
     "Fix write perms on output/work dirs; avoid binding read-only."),

    (re.compile(r"Read-only file system", re.I),
     "I/O: Read-only filesystem",
     "Don't bind outputs as read-only; check -B flags."),

    (re.compile(r"ValueError: .*BIDS root.*does not exist", re.I),
     "BIDS: root missing",
     "Check mounted BIDS path (-B) and container paths."),

    (re.compile(r"BIDS root file structure is invalid|BIDS validation .* failed", re.I),
     "BIDS: invalid structure",
     "Run the BIDS Validator; fix missing/invalid metadata."),

    (re.compile(r"PhaseEncodingDirection.*not found|No fieldmaps found; SDC disabled", re.I),
     "BIDS: missing PEdir/fieldmaps",
     "Add PhaseEncodingDirection or use --use-syn-sdc / other SDC methods."),

    (re.compile(r"SliceTiming.*missing|slicetiming .* will be ignored", re.I),
     "BIDS: slice timing missing/invalid",
     "Consider --ignore slicetiming (typical for some ADNI exports)."),

    (re.compile(r"No functional( scans)? were found for the participant|No BOLD files found|Selected data .* yielded no BOLD", re.I),
     "Inputs: no BOLD detected (log)",
     "fMRIPrep did not find BOLD based on selection/filtering."),

    (re.compile(r"TemplateFlow.*(Error|not found|Could not fetch template|Dataset could not be found)", re.I),
     "TemplateFlow cache/bind issue",
     "Bind TEMPLATEFLOW cache or allow caching under $HOME/.cache/templateflow."),

    (re.compile(r"antsRegistration.*Command failed|ANTs\\) Exception", re.I),
     "ANTs: registration failed",
     "Often OOM or bad inputs; try more memory or fewer output spaces."),

    (re.compile(r"segmentation fault|core dumped", re.I),
     "Crash: segmentation fault",
     "Generic crash; check earlier errors and memory."),

    (re.compile(r"Node .* failed|Crash file written to|Traceback \\(most recent call last\\):", re.I),
     "Nipype node crash",
     "Inspect crashfile for node name and traceback."),

    (re.compile(r"FileNotFoundError: .*bold.*", re.I),
     "Inputs: bold file missing",
     "Filter selected no BOLD; check --bids-filter-file / sessions."),

    (re.compile(r"json.decoder.JSONDecodeError|Expecting property name enclosed in double quotes", re.I),
     "BIDS filter JSON invalid",
     "Fix malformed --bids-filter-file JSON."),

    # NEW: SyN SDC PEdir error
    (re.compile(r"Fieldmap-less.*PhaseEncodingDirection.*absent", re.I),
     "SDC: SyN requires PhaseEncodingDirection",
     "Fieldmap-less (SyN) SDC requested but PhaseEncodingDirection missing; either add PEdir or drop --use-syn-sdc."),
]

LOG_EXTS = ('.out', '.err', '.log', '.txt')
CRASH_GLOBS = [
    'derivatives/fmriprep/sub-*/log/*crash*.txt',
    'derivatives/fmriprep/sub-*/log/*crash*.tsv',
    'sub-*/log/*crash*.txt',
    'sub-*/log/*crash*.tsv',
]

def guess_subject_session_from_text(text: str):
    sub = None; ses = None
    m = re.search(r"\\bsub-[A-Za-z0-9]+", text)
    if m: sub = m.group(0)
    m2 = re.search(r"\\bses-[A-Za-z0-9]+", text)
    if m2: ses = m2.group(0)
    m3 = re.search(r"\\b(M\\d{3})\\b", text)
    if not ses and m3: ses = f"ses-{m3.group(1)}"
    return sub, ses

def classify_text(text: str):
    for entry in PATTERNS:
        if not isinstance(entry, tuple) or len(entry) < 2:
            continue
        rx = entry[0]; cat = entry[1]
        note = entry[2] if len(entry) > 2 else ""
        if hasattr(rx, "search") and rx.search(text):
            for line in text.splitlines():
                if rx.search(line):
                    return cat, (line.strip()[:240])
            return cat, note or "Matched pattern"
    for line in text.splitlines():
        if re.search(r"error|failed|exception|Traceback|not found|No such file", line, re.I):
            return "Unclassified error", (line.strip()[:240])
    return "Unknown", ""

def read_tail(p: Path, n: int = 20000) -> str:
    try:
        s = p.read_text(errors='ignore')
        return s[-n:]
    except Exception:
        return ''

def bold_status_on_disk(bids_root: Path|None, subject: str|None, session: str|None):
    if not bids_root or not subject:
        return None
    subj_dir = bids_root / subject
    if not subj_dir.exists():
        return None
    if session:
        ses_clean = session.replace('ses-', '')
        func_dir = subj_dir / f'ses-{ses_clean}' / 'func'
        if not func_dir.exists():
            any_bold = list(subj_dir.glob('ses-*/func/*bold.nii.gz'))
            return 'subject_has_no_bold' if len(any_bold)==0 else 'session_has_no_bold'
        bolds = list(func_dir.glob('*bold.nii.gz'))
        if len(bolds)==0:
            any_bold = list(subj_dir.glob('ses-*/func/*bold.nii.gz'))
            return 'subject_has_no_bold' if len(any_bold)==0 else 'session_has_no_bold'
        return None
    any_bold = list(subj_dir.glob('ses-*/func/*bold.nii.gz'))
    return 'subject_has_no_bold' if len(any_bold)==0 else None

def saw_session_filter(text: str) -> bool:
    return ("--session-label" in text) or ("\"session\"" in text and "bids-filter-file" in text)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--logs', action='append', default=[], help='Logs dir (repeatable)')
    ap.add_argument('--crashes', action='append', default=[], help='Derivatives dir (repeatable)')
    ap.add_argument('--bids', type=str, default=None, help='BIDS root (for BOLD checks)')
    ap.add_argument('--out', required=True, help='Output CSV')
    args = ap.parse_args()

    bids_root = Path(args.bids).resolve() if args.bids else None
    if bids_root and not bids_root.exists():
        print(f'[WARN] BIDS root does not exist: {bids_root} — skipping BOLD checks.')
        bids_root = None

    log_files = []
    for base in args.logs:
        b = Path(base)
        if b.is_file():
            if b.suffix.lower() in LOG_EXTS:
                log_files.append(b)
        elif b.is_dir():
            for suf in LOG_EXTS:
                log_files.extend(b.rglob(f'*{suf}'))

    crash_files = []
    for cd in args.crashes:
        c = Path(cd)
        if c.is_file():
            crash_files.append(c)
        elif c.is_dir():
            for pat in CRASH_GLOBS:
                crash_files.extend(c.rglob(pat))

    rows = []

    # Logs
    for p in sorted(set(log_files)):
        tail = read_tail(p, n=40000)
        sub, ses = guess_subject_session_from_text(tail + ' ' + p.name)
        cat, detail = classify_text(tail)

        bs = bold_status_on_disk(bids_root, sub, ses)
        if bs == 'subject_has_no_bold':
            rows.append({'source':'log','file':str(p),'subject':sub or '','session':ses or '',
                         'category':'Inputs: no BOLD for subject',
                         'detail':'Subject has no usable BOLD images across all sessions (filesystem check)'})
        elif bs == 'session_has_no_bold':
            rows.append({'source':'log','file':str(p),'subject':sub or '','session':ses or '',
                         'category':'Inputs: session has no BOLD',
                         'detail':'This session directory exists but contains no BOLD images (filesystem check)'})
        if cat == 'Inputs: no BOLD detected (log)' and bids_root and sub:
            subj_dir = bids_root / sub
            any_bold_elsewhere = subj_dir.exists() and bool(list(subj_dir.glob('ses-*/func/*bold.nii.gz')))
            if any_bold_elsewhere and saw_session_filter(tail):
                rows.append({'source':'log','file':str(p),'subject':sub or '','session':ses or '',
                             'category':'Inputs: BOLD exists in other sessions (filtered out)',
                             'detail':'Log says no BOLD, but BOLD exists in other sessions; selection likely excluded them.'})
        if cat not in ('Unknown',''):
            rows.append({'source':'log','file':str(p),'subject':sub or '','session':ses or '',
                         'category':cat,'detail':detail})

    # Crashfiles
    for p in sorted(set(crash_files)):
        txt = read_tail(p, n=60000)
        sub, ses = guess_subject_session_from_text(txt + ' ' + p.name)
        m = re.search(r'Node: ([^\\n]+)', txt)
        node = m.group(1).strip() if m else ''

        cat, detail = classify_text(txt)

        bs = bold_status_on_disk(bids_root, sub, ses)
        if bs == 'subject_has_no_bold':
            rows.append({'source':'crashfile','file':str(p),'subject':sub or '','session':ses or '',
                         'category':'Inputs: no BOLD for subject',
                         'detail':'Subject has no usable BOLD images across all sessions (filesystem check)'})
        elif bs == 'session_has_no_bold':
            rows.append({'source':'crashfile','file':str(p),'subject':sub or '','session':ses or '',
                         'category':'Inputs: session has no BOLD',
                         'detail':'This session directory exists but contains no BOLD images (filesystem check)'})
        if cat == 'Inputs: no BOLD detected (log)' and bids_root and sub:
            subj_dir = bids_root / sub
            any_bold_elsewhere = subj_dir.exists() and bool(list(subj_dir.glob('ses-*/func/*bold.nii.gz')))
            if any_bold_elsewhere:
                rows.append({'source':'crashfile','file':str(p),'subject':sub or '','session':ses or '',
                             'category':'Inputs: BOLD exists in other sessions (filtered out)',
                             'detail':'Crash says no BOLD, but BOLD exists in other sessions; selection likely excluded them.'})
        if node and cat == 'Unknown':
            cat = 'Nipype node crash'; detail = f'Node: {node}'
        rows.append({'source':'crashfile','file':str(p),'subject':sub or '','session':ses or '',
                     'category':cat if cat else 'Unknown','detail':detail or 'see crashfile'})

    outp = Path(args.out)
    outp.parent.mkdir(parents=True, exist_ok=True)
    with outp.open('w', newline='') as f:
        wr = csv.DictWriter(f, fieldnames=['source','file','subject','session','category','detail'])
        wr.writeheader()
        for r in rows:
            wr.writerow(r)

    counts = {}
    for r in rows:
        counts[r['category']] = counts.get(r['category'], 0) + 1
    print(f'Wrote {len(rows)} rows to {outp}')
    if counts:
        print('\nSummary by category:')
        for k in sorted(counts, key=lambda k: (-counts[k], k)):
            print(f'{counts[k]:4d}  {k}')
    else:
        print('No errors classified.')

if __name__ == '__main__':
    main()
