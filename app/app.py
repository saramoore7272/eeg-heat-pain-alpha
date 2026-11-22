"""Run with: python -m streamlit run app/app.py --server.address 127.0.0.1"""

from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory

import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.ticker import MaxNLocator
import numpy as np
import pandas as pd
import streamlit as st

from eeg import analyze_heat_recording, analyze_window, open_brainvision, stage_upload


ROOT = Path(__file__).resolve().parents[1]
PROJECT_DATA = ROOT / "data" / "raw" / "ds008349-2.0.1"
PLAN = json.loads((ROOT / "c3-c4-alpha-analysis-lock.json").read_text(encoding="utf-8"))
BLUE = "#235B7E"
TEAL = "#187467"
RUST = "#9A512F"
INK = "#273644"
GRID = "#DDE6EB"
TASK_NAMES = {
    "thermalactive": "Rated heat",
    "audioactive": "Rated sound",
    "restingopen": "Eyes-open rest",
}
RECORDING_ERRORS = (ValueError, OSError, RuntimeError, KeyError, IndexError, pd.errors.ParserError)


def project_label(path):
    subject, task, *_ = path.stem.split("_")
    task = task.removeprefix("task-")
    return f"{subject} · {TASK_NAMES.get(task, task)}"


def choose_recording():
    st.sidebar.header("Recording")
    project_files = sorted(PROJECT_DATA.glob("sub-*/eeg/*_eeg.vhdr"))
    modes = ["Project recording", "Upload BrainVision"] if project_files else ["Upload BrainVision"]
    source = st.sidebar.radio("Source", modes)
    if source == "Project recording":
        default = next((i for i, path in enumerate(project_files) if path.name ==
                        "sub-086_task-thermalactive_eeg.vhdr"), 0)
        header = st.sidebar.selectbox("Recording", project_files, index=default, format_func=project_label)
        return header, True, project_label(header)

    upload_revision = st.session_state.get("upload_revision", 0)
    with st.sidebar.form("brainvision_files", clear_on_submit=False):
        files = st.file_uploader("BrainVision files", type=["vhdr", "vmrk", "eeg"], accept_multiple_files=True,
                                 key=f"brainvision-{upload_revision}")
        st.caption("Select the matching .vhdr, .vmrk, and .eeg together.")
        open_clicked = st.form_submit_button("Open recording", type="primary", width="stretch")
    if open_clicked:
        temporary = TemporaryDirectory(prefix="brainvision-viewer-")
        try:
            header = stage_upload(files, Path(temporary.name))
            opened = open_brainvision(header)
        except RECORDING_ERRORS as error:
            temporary.cleanup()
            st.sidebar.error(str(error))
        else:
            previous = st.session_state.get("upload")
            st.session_state["upload"] = (temporary, header)
            st.session_state["recording_cache"] = ((header, False), opened)
            if previous is not None:
                previous[0].cleanup()
    upload = st.session_state.get("upload")
    if upload is None:
        st.info("Choose a project recording or upload a complete BrainVision recording to get started.")
        st.stop()
    temporary, header = upload
    if st.sidebar.button("Remove uploaded recording", width="stretch"):
        st.session_state.pop("upload")
        st.session_state.pop("recording_cache", None)
        st.session_state["upload_revision"] = upload_revision + 1
        temporary.cleanup()
        st.rerun()
    return header, False, header.stem


def load_recording(header, project):
    key = (header, project)
    cached = st.session_state.get("recording_cache")
    if cached is not None and cached[0] == key:
        return cached[1]
    recording = open_brainvision(header, project=project)
    st.session_state["recording_cache"] = (key, recording)
    return recording


def format_duration(seconds):
    minutes, remainder = divmod(int(seconds), 60)
    if minutes:
        return f"{minutes}m {remainder:02d}s"
    return f"{seconds:.1f} s"


def view_controls(recording, project_heat):
    source_key = sha256(str(recording.header).encode("utf-8")).hexdigest()[:12]
    total_seconds = recording.duration
    choices = [seconds for seconds in (5, 10, 20, 30) if seconds < total_seconds]
    if total_seconds <= 30:
        choices.append(total_seconds)
    default_length = 10 if 10 in choices else choices[-1]
    with st.container(border=True):
        first, second, third = st.columns([1, 1, 2])
        window_length = second.selectbox(
            "Window length", choices, index=choices.index(default_length), key=f"length-{source_key}",
            format_func=lambda x: f"{x:.3f}".rstrip("0").rstrip(".") + " s",
        )
        max_start = max(0.0, total_seconds - window_length)
        default_start = min(25.0, max_start) if project_heat else 0.0
        start_seconds = first.number_input(
            "Start time (s)", min_value=0.0, max_value=max_start,
            value=default_start, step=0.5, format="%.3f",
            key=f"start-{source_key}-{window_length}", disabled=max_start == 0,
        )
        names = tuple(dict.fromkeys([*recording.scalp, *recording.eyes])) or tuple(recording.raw.ch_names)
        default_channels = [name for name in ("C3", "Cz", "C4") if name in names] or list(names[:3])
        channels = third.multiselect(
            "Trace channels", names, default=default_channels, max_selections=6, key=f"traces-{source_key}",
        )

    start = min(round(start_seconds * recording.rate), recording.raw.n_times - 1)
    stop = min(start + max(1, round(window_length * recording.rate)), recording.raw.n_times)
    return start, stop, channels, source_key


def visible_markers(recording, start, stop):
    markers = recording.raw.annotations
    onsets = markers.onset - recording.raw.first_time
    in_window = (onsets >= start / recording.rate) & (onsets < stop / recording.rate)
    return pd.DataFrame({
        "Time (s)": onsets[in_window],
        "Marker": markers.description[in_window],
    })


def plot_style(axis):
    axis.spines[["top", "right"]].set_visible(False)
    axis.spines[["bottom", "left"]].set_color("#8193A0")
    axis.tick_params(axis="both", colors=INK, labelsize=10)
    axis.grid(axis="x", color=GRID, linewidth=0.65)
    axis.set_axisbelow(True)


def show_plot(fig):
    st.pyplot(fig, width="stretch", clear_figure=True)
    plt.close(fig)


def trace_figure(recording, start, stop, channels, center):
    data, times = recording.raw.get_data(picks=channels, start=start, stop=stop, return_times=True)
    fig, axes = plt.subplots(len(channels), 1, figsize=(8.8, 1.13 * len(channels) + 0.55),
                             sharex=True, squeeze=False, layout="constrained")
    markers = visible_markers(recording, start, stop)
    types = recording.raw.get_channel_types(picks=channels)
    for axis, values, name, kind in zip(axes[:, 0], data, channels, types):
        voltage = kind in {"eeg", "eog", "ecg", "emg"}
        values = values * 1e6 if voltage else values
        if center and voltage and np.isfinite(values).any():
            values = values - np.nanmedian(values)
        axis.plot(times, values, color=BLUE, linewidth=0.78)
        for x in markers["Time (s)"]:
            axis.axvline(x, color=RUST, linewidth=0.85, linestyle="--")
        axis.yaxis.set_major_locator(MaxNLocator(3))
        axis.set_ylabel(f"{name}\n{'µV' if voltage else 'raw units'}", rotation=0, ha="right",
                        va="center", fontsize=11, color=INK, labelpad=17)
        plot_style(axis)
    axes[-1, 0].set_xlabel("Recording time (s)", color=INK)
    if stop - start > 1:
        axes[-1, 0].set_xlim(start / recording.rate, stop / recording.rate)
    return fig


def alpha_figure(times, powers, passed, groups=None):
    fig, axis = plt.subplots(figsize=(8.8, 3.4), layout="constrained")
    colors = {"C3": BLUE, "C4": TEAL}
    markers = {"C3": "o", "C4": "s"}
    has_values = False
    for site, data in powers.items():
        values = np.asarray(data)
        finite = np.isfinite(values) & (values > 0)
        if not finite.any():
            continue
        has_values = True
        for group in np.unique(groups) if groups is not None else [0]:
            subset = (groups == group) if groups is not None else np.ones(len(times), dtype=bool)
            axis.plot(times[subset], np.where(finite[subset], values[subset], np.nan), color=colors[site],
                      alpha=0.50, linewidth=1)
        for accept, face in ((True, colors[site]), (False, "white")):
            mask = (passed == accept) & finite
            axis.scatter(times[mask], values[mask], marker=markers[site], s=27, facecolor=face,
                         edgecolor=colors[site], linewidth=1.0, zorder=3)
    if not has_values:
        plt.close(fig)
        return None
    handles = [
        Line2D([], [], marker=markers[site], markerfacecolor=colors[site], markeredgecolor=colors[site],
               linestyle="none", label=site)
        for site in powers
        if np.any(np.isfinite(powers[site]) & (np.asarray(powers[site]) > 0))
    ]
    handles.append(Line2D([], [], marker="o", markerfacecolor="white", markeredgecolor=INK,
                          linestyle="none", label="Screened out"))
    axis.legend(handles=handles, loc="best", frameon=False, ncol=len(handles), fontsize=10)
    axis.set_yscale("log")
    axis.set_xlabel("Recording time (s)", color=INK)
    axis.set_ylabel("8–13 Hz power (µV²)", color=INK)
    plot_style(axis)
    return fig


def cached_heat_analysis(recording):
    key = recording.header
    cached = st.session_state.get("heat_screen")
    if cached is not None and cached[0] == key:
        return cached[1]
    result = analyze_heat_recording(recording, PLAN)
    st.session_state["heat_screen"] = (key, result)
    return result


def screening_tab(window, heat, heat_error):
    if heat is not None:
        st.subheader("Locked rated-heat screen")
        a, b, c = st.columns(3)
        a.metric("Seconds passed", f"{heat.blocks['Passed'].sum()} / {len(heat.seconds)}")
        b.metric("Blocks with ≥5 passing seconds", f"{heat.blocks['Eligible'].sum()} / {len(heat.blocks)}")
        c.metric("Temperature-matched repeat pairs", heat.matched_pairs)
        st.dataframe(heat.blocks.drop(columns="Eligible"), hide_index=True, width="stretch")
        omitted = ", ".join(heat.omitted) if heat.omitted else "None"
        st.caption(f"Seconds 25–35 after each block marker. Calibration selected channels to omit: {omitted}.")
    elif heat_error:
        st.warning(heat_error)

    st.subheader("Visible window screen")
    if window.screen.empty:
        st.info("Screening needs at least one complete second and a scalp EEG channel in the selected window.")
        return
    cols = st.columns(3)
    cols[0].metric("Passed", f"{window.screen['Pass'].sum()} / {len(window.screen)} s")
    cols[1].metric("Scalp flags", int(window.screen["Scalp failures"].gt(0).sum()))
    eye_count = "Unavailable" if not window.eye_checked else int(
        (~np.isfinite(window.screen["Eye swing (µV)"]) |
         (window.screen["Eye swing (µV)"] >= PLAN["screen"]["primary_eog_peak_to_peak_microvolts_exclusive"])).sum()
    )
    cols[2].metric("Eye flags", eye_count)
    st.caption("Scalp criterion: 0.5–150 µV peak to peak per channel. Eye criterion: <100 µV after 1–10 Hz filtering."
               if window.eye_checked else "Scalp-only screen: 0.5–150 µV peak to peak per channel. Eye screening is unavailable.")
    table = window.screen.copy()
    table["Pass"] = table["Pass"].map({True: "Pass", False: "Flagged"})
    st.dataframe(table.round(2), hide_index=True, width="stretch")
    if heat is not None:
        st.caption("The visible-window screen uses every scalp channel. The locked heat screen also applies channel omissions and task checks.")


def alpha_tab(window, heat, source_key):
    st.subheader("C3/C4 alpha power")
    if heat is not None:
        scope = st.radio("Plot range", ["Visible window", "Locked heat blocks"], horizontal=True,
                         key=f"alpha-range-{source_key}")
    else:
        scope = "Visible window"
    if scope == "Locked heat blocks":
        table = heat.seconds
        powers = {name: table[name].to_numpy() for name in ("C3", "C4")}
        references = {"C3": "local", "C4": "local"}
        fig = alpha_figure(table["Time (s)"].to_numpy(), powers, table["Pass"].to_numpy(),
                           table["Block"].to_numpy())
    else:
        references = window.references
        fig = alpha_figure(window.screen["Time (s)"].to_numpy(), window.alpha, window.screen["Pass"].to_numpy())
    if fig is None:
        st.info("Alpha power needs a full second of EEG, a C3 or C4 channel, and a sampling rate above 26 Hz.")
        return
    show_plot(fig)
    reference_text = " · ".join(f"{name}: {method} reference" for name, method in references.items())
    st.caption(f"One-second Hann spectra, summed over 8–13 Hz. {reference_text}. Hollow markers failed the selected screen.")


def main():
    st.set_page_config(page_title="EEG recording viewer", page_icon="〰️", layout="wide")
    st.html("""
        <style>
        .block-container {max-width: 1160px; padding: 2.3rem clamp(1rem, 3vw, 2.5rem) 3rem;}
        [data-testid="stMetricValue"] {font-variant-numeric: tabular-nums;}
        [data-testid="stMetricValue"] > div {font-size: clamp(1.35rem, 2.5vw, 1.95rem);}
        [data-testid="stHeadingWithActionElements"] h1 {letter-spacing: -.035em;}
        </style>
    """)
    st.title("EEG recording viewer")
    st.caption("Inspect BrainVision signals, screening flags, and central alpha power.")
    header, project, label = choose_recording()
    try:
        recording = load_recording(header, project)
    except RECORDING_ERRORS as error:
        st.error(f"Unable to open this recording. {error}")
        st.stop()

    project_heat = project and header.name.endswith("_task-thermalactive_eeg.vhdr")
    st.subheader(label)
    metrics = st.columns(4)
    metrics[0].metric("Scalp channels", len(recording.scalp))
    metrics[1].metric("Sample rate", f"{recording.rate:,.3f}".rstrip("0").rstrip(".") + " Hz")
    metrics[2].metric("Duration", format_duration(recording.duration))
    metrics[3].metric("Markers", len(recording.raw.annotations))
    start, stop, channels, source_key = view_controls(recording, project_heat)

    try:
        window = analyze_window(recording, start, stop, PLAN)
    except RECORDING_ERRORS as error:
        st.error(f"Unable to read the selected window. {error}")
        st.stop()
    heat, heat_error = None, None
    if project_heat:
        try:
            heat = cached_heat_analysis(recording)
        except RECORDING_ERRORS as error:
            heat_error = f"Locked heat screen unavailable. {error}"

    traces, screening, alpha = st.tabs(["Raw traces", "Screening", "C3/C4 alpha"])
    with traces:
        start_s, stop_s = start / recording.rate, stop / recording.rate
        st.subheader("Raw EEG traces")
        st.caption(f"{start_s:.2f}–{stop_s:.2f} s · Dashed lines mark recorded events.")
        center = st.checkbox("Center voltage traces for display", value=True)
        if channels:
            show_plot(trace_figure(recording, start, stop, channels, center))
        else:
            st.info("Select at least one trace channel above.")
        markers = visible_markers(recording, start, stop)
        if not markers.empty:
            st.dataframe(markers.round(3), hide_index=True, width="stretch")
    with screening:
        screening_tab(window, heat, heat_error)
    with alpha:
        alpha_tab(window, heat, source_key)


if __name__ == "__main__":
    main()
