"""BrainVision loading, window screening, and C3/C4 power for the viewer."""

from dataclasses import dataclass
from itertools import combinations
import json
from pathlib import Path, PureWindowsPath
import re
import shutil

import mne
import numpy as np
import pandas as pd
from scipy import signal


GENERIC_EOG = ("HEOGL", "HEOGR", "VEOGb", "HEOG", "VEOG", "EOG", "EOG1", "EOG2",
               "EOG-L", "EOG-R", "EOG-H", "EOG-V")
GENERIC_AUX = {"ecg", "ekg", "emg", "gsr", "eda", "rating", "stim", "thermode"}
CENTERS = ("C3", "C4")


@dataclass
class Recording:
    raw: mne.io.BaseRaw
    scalp: tuple[str, ...]
    eyes: tuple[str, ...]
    header: Path
    metadata: dict

    @property
    def rate(self):
        return float(self.raw.info["sfreq"])

    @property
    def duration(self):
        return self.raw.n_times / self.rate


@dataclass
class Window:
    start: int
    stop: int
    screen: pd.DataFrame
    alpha: dict[str, np.ndarray]
    references: dict[str, str]
    eye_checked: bool


@dataclass
class HeatScreen:
    blocks: pd.DataFrame
    seconds: pd.DataFrame
    omitted: tuple[str, ...]
    matched_pairs: int


def brainvision_reference(header, key):
    """Read a filename from the small BrainVision metadata file."""
    with header.open("rb") as handle:
        raw = handle.read(1024 * 1024 + 1)
    if len(raw) > 1024 * 1024:
        raise ValueError(f"{header.name} exceeds the 1 MB metadata limit.")
    try:
        header_text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        header_text = raw.decode("cp1252", errors="replace")
    common = re.search(r"(?im)^\[Common Infos\]\s*$\n(.*?)(?=^\[|\Z)",
                       header_text.replace("\r\n", "\n"), flags=re.DOTALL)
    if common is None:
        raise ValueError(f"{header.name} has no BrainVision Common Infos section.")
    values = re.findall(rf"(?im)^[ \t]*{re.escape(key)}[ \t]*=[ \t]*([^\n]+)$", common[1])
    if len(values) != 1 or not values[0].strip():
        raise ValueError(f"{header.name} must contain one {key} reference.")
    return values[0].strip().strip('"')


def simple_filename(name):
    return (
        bool(name) and name not in {".", ".."}
        and Path(name).name == name and PureWindowsPath(name).name == name
        and not PureWindowsPath(name).drive
        and not any(ord(character) < 32 for character in name)
    )


def stage_upload(files, directory):
    """Copy one trio to a private directory and validate its file references."""
    by_suffix = {}
    for file in files:
        if not simple_filename(file.name):
            raise ValueError("Use the original BrainVision filenames without any folder paths.")
        suffix = Path(file.name).suffix.lower()
        if suffix not in {".vhdr", ".vmrk", ".eeg"} or suffix in by_suffix:
            raise ValueError("Select exactly one .vhdr, one .vmrk, and one .eeg file.")
        by_suffix[suffix] = file
    if set(by_suffix) != {".vhdr", ".vmrk", ".eeg"}:
        raise ValueError("Select all three files: .vhdr, .vmrk, and .eeg.")

    # Only copy the large binary once the metadata files agree.
    for suffix in (".vhdr", ".vmrk"):
        upload = by_suffix[suffix]
        upload.seek(0)
        payload = upload.read(1024 * 1024 + 1)
        if len(payload) > 1024 * 1024:
            raise ValueError(f"{upload.name} exceeds the 1 MB metadata limit.")
        (directory / upload.name).write_bytes(payload)
    header = directory / by_suffix[".vhdr"].name
    markers = directory / by_suffix[".vmrk"].name
    for origin, field, suffix in (
        (header, "DataFile", ".eeg"), (header, "MarkerFile", ".vmrk"),
        (markers, "DataFile", ".eeg"),
    ):
        reference = brainvision_reference(origin, field)
        if not simple_filename(reference) or reference != by_suffix[suffix].name:
            raise ValueError(f"{origin.name} refers to {reference!r}. Select the matching original {suffix} file.")

    upload = by_suffix[".eeg"]
    upload.seek(0)
    with (directory / upload.name).open("wb") as target:
        shutil.copyfileobj(upload, target, length=1024 * 1024)
    return header


def project_prefix(header):
    return header.with_name(header.name.removesuffix("_eeg.vhdr"))


def open_brainvision(header, *, project=False):
    options = {"preload": False, "ignore_marker_types": True, "verbose": "ERROR"}
    scalp = None
    metadata = {}
    if project:
        prefix = project_prefix(header)
        channels_path = Path(f"{prefix}_channels.tsv")
        metadata_path = Path(f"{prefix}_eeg.json")
        if metadata_path.is_file():
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if channels_path.is_file():
            table = pd.read_csv(channels_path, sep="\t")
            scalp = tuple(table.loc[table["type"].eq("EEG"), "name"])
            options["eog"] = tuple(table.loc[table["type"].eq("EOG"), "name"])
            options["misc"] = tuple(table.loc[~table["type"].isin(["EOG", "EEG"]), "name"])
    if scalp is None:
        options["eog"] = GENERIC_EOG
    raw = mne.io.read_raw_brainvision(header, **options)
    if scalp is None:
        scalp = tuple(name for name, kind in zip(raw.ch_names, raw.get_channel_types())
                      if kind == "eeg" and name.casefold() not in GENERIC_AUX and "eog" not in name.casefold())
    eyes = tuple(name for name, kind in zip(raw.ch_names, raw.get_channel_types())
                 if kind == "eog" or (not project and "eog" in name.casefold()))
    if raw.n_times < 1:
        raise ValueError("The signal file contains no EEG samples.")
    return Recording(raw=raw, scalp=scalp, eyes=eyes, header=header, metadata=metadata)


def amplitude_failures(data, limits):
    amplitude = np.ptp(data, axis=-1) * 1e6
    return ~np.isfinite(amplitude) | (amplitude < limits[0]) | (amplitude > limits[1])


def power_at_sites(data, channel_names, rate, plan):
    """Return integrated alpha density in µV² for each available center."""
    if rate / 2 <= plan["alpha"]["frequency_bins_hz_inclusive"][1]:
        return {}, {}
    canonical = {name.casefold(): index for index, name in enumerate(channel_names)}
    power, references = {}, {}
    for name in CENTERS:
        if name.casefold() not in canonical:
            continue
        trace = data[canonical[name.casefold()]]
        neighbors = plan["alpha"]["local_reference"][name]
        if all(channel.casefold() in canonical for channel in neighbors):
            trace = trace - data[[canonical[channel.casefold()] for channel in neighbors]].mean(axis=0)
            references[name] = "local"
        else:
            references[name] = "acquisition"
        frequency, density = signal.periodogram(trace, fs=rate, window="hann", detrend="constant", axis=-1)
        low, high = plan["alpha"]["frequency_bins_hz_inclusive"]
        usable = (frequency >= low) & (frequency <= high)
        if usable.any():
            power[name] = density[..., usable].sum(axis=-1) * (rate / trace.shape[-1]) * 1e12
    return power, references


def eye_peaks(data, rate, band):
    sos = signal.butter(3, band, fs=rate, btype="bandpass", output="sos")
    return signal.sosfiltfilt(sos, data, axis=-1)


def analyze_window(recording, start, stop, plan):
    rate = recording.rate
    length = max(1, round(rate))
    count = (stop - start) // length
    schema = ["Time (s)", "Scalp failures", "Eye swing (µV)", "Pass"]
    if not count or not recording.scalp:
        return Window(start, stop, pd.DataFrame(columns=schema), {}, {}, False)
    end = start + count * length
    data = recording.raw.get_data(picks=list(recording.scalp), start=start, stop=end)
    data = data.reshape(len(recording.scalp), count, length)
    screen = plan["screen"]
    failures = amplitude_failures(data, screen["eeg_peak_to_peak_microvolts_inclusive"]).sum(axis=0)
    eyes = np.full(count, np.nan)
    buffer = 3 * length
    lo, hi = max(start - buffer, 0), min(end + buffer, recording.raw.n_times)
    # Third-order band-pass padding requires more than 21 samples.
    eye_checked = bool(recording.eyes and rate / 2 > screen["eog_filter_hz"][1] and hi - lo > 21)
    if eye_checked:
        eye_data = recording.raw.get_data(picks=list(recording.eyes), start=lo, stop=hi)
        slow = eye_peaks(eye_data, rate, screen["eog_filter_hz"])[:, start - lo:end - lo]
        eyes = np.ptp(slow.reshape(len(recording.eyes), count, length), axis=-1).max(axis=0) * 1e6
    passed = failures == 0
    if eye_checked:
        passed &= np.isfinite(eyes) & (eyes < screen["primary_eog_peak_to_peak_microvolts_exclusive"])
    table = pd.DataFrame({
        "Time (s)": (start + np.arange(count) * length) / rate,
        "Scalp failures": failures, "Eye swing (µV)": eyes, "Pass": passed,
    })
    power, references = power_at_sites(data, recording.scalp, rate, plan)
    return Window(start, stop, table, power, references, eye_checked)


def heat_events(recording, plan):
    expected = plan["expected_structure"]
    screen = plan["screen"]
    needed = set(screen["eog_channels"]) | {"stim", "thermode", "rating"}
    protected = {"C3", "Cz", "C4", *(name for group in plan["alpha"]["local_reference"].values() for name in group)}
    if (recording.rate != expected["sfreq_hz"] or len(recording.scalp) != expected["eeg_channels"]
            or recording.metadata.get("EEGReference") != expected["acquisition_reference"]
            or not protected.issubset(recording.scalp)
            or not needed.issubset(recording.raw.ch_names)):
        raise ValueError("This recording does not have the montage and task channels required for the locked rated-heat screen.")
    path = Path(f"{project_prefix(recording.header)}_events.tsv")
    if not path.is_file():
        raise ValueError("The rated-heat event table is unavailable.")
    events = pd.read_csv(path, sep="\t")
    levels = expected["levels"]
    labels = [f"t{i:02d}/p{level}" for i, level in enumerate(levels, 1)] + ["t10/end"]
    samples = events["sample"].to_numpy(dtype=int)
    onset = events["onset"].to_numpy(dtype=float)
    annotations = recording.raw.annotations
    if labels != events["trial_type"].tolist() or labels != annotations.description.tolist():
        raise ValueError("The recording and event table do not have the locked heat block order.")
    tolerance = expected["onset_sample_and_marker_tolerance_ms"]
    if (np.max(np.abs(np.rint(onset * recording.rate) - samples)) > tolerance
            or np.max(np.abs(onset - annotations.onset)) * 1000 > tolerance + 1e-6
            or (samples < 0).any() or (samples >= recording.raw.n_times).any()
            or (np.diff(samples) < 38 * recording.rate).any()):
        raise ValueError("The heat markers disagree or do not support the locked windows.")
    return samples[:-1], levels


def analyze_heat_recording(recording, plan):
    """Apply the locked recording-level screen without fitting a group model."""
    samples, levels = heat_events(recording, plan)
    screen = plan["screen"]
    rate = int(recording.rate)
    names = recording.scalp
    eyes = screen["eog_channels"]
    limits = screen["eeg_peak_to_peak_microvolts_inclusive"]
    neighbor_names = plan["alpha"]["local_reference"].values()
    protected = {"C3", "Cz", "C4", *(name for group in neighbor_names for name in group)}
    nomination_counts = np.zeros(len(names), dtype=int)
    segments = []
    for sample, level in zip(samples, levels):
        picks = [*names, *eyes, "stim", "thermode", "rating"]
        data = recording.raw.get_data(picks=picks, start=sample + 12 * rate, stop=sample + 38 * rate)
        before, after = screen["eeg_calibration_seconds"]
        training = data[:len(names), (before - 12) * rate:(after - 12) * rate].reshape(len(names), after - before, rate)
        nomination_counts += amplitude_failures(training, limits).sum(axis=1)
        before, after = screen["matching_window_seconds"]
        span = slice((before - 12) * rate, (after - 12) * rate)
        n = after - before
        scalp = data[:len(names), span].reshape(len(names), n, rate)
        failed = amplitude_failures(scalp, limits)
        slow = eye_peaks(data[len(names):len(names) + len(eyes)], rate, screen["eog_filter_hz"])
        eye = np.ptp(slow[:, span].reshape(len(eyes), n, rate), axis=-1).max(axis=0) * 1e6
        alpha, _ = power_at_sites(scalp, names, rate, plan)
        stimulus, temperature, rating = data[-3:, span].reshape(3, n, rate)
        valid = ((np.isfinite(stimulus) & np.isclose(stimulus, level)).all(axis=1)
                 & (np.isfinite(temperature) & (temperature > 0)).all(axis=1)
                 & (np.isfinite(rating) & (rating >= 0) & (rating != 999)).all(axis=1))
        steady = np.ptp(rating, axis=-1) <= screen["max_rating_span_per_second_inclusive"]
        segments.append((sample, level, failed, eye, alpha, valid, steady, np.median(temperature, axis=1)))

    ranked = sorted((i for i, name in enumerate(names) if name not in protected and nomination_counts[i] > 0),
                    key=lambda i: (-nomination_counts[i], names[i]))
    omitted_indices = ranked[:screen["omit_up_to_n_scalp_channels"]]
    keep = np.ones(len(names), dtype=bool)
    keep[omitted_indices] = False
    minimum = screen["min_common_passing_seconds"]
    block_rows, seconds, pairs_input = [], [], []
    for i, (sample, level, failed, eye, alpha, valid, steady, temperature) in enumerate(segments, 1):
        scalp = ~failed[keep].any(axis=0)
        eye_pass = np.isfinite(eye) & (eye < screen["primary_eog_peak_to_peak_microvolts_exclusive"])
        labels = valid & steady
        power_is_valid = np.logical_and.reduce([np.isfinite(values) & (values > 0) for values in alpha.values()])
        passed = scalp & eye_pass & labels & power_is_valid
        block_rows.append({"Block": i, "Heat level": level, "Scalp pass": int(scalp.sum()),
                           "Eye pass": int(eye_pass.sum()), "Task labels and steady rating": int(labels.sum()),
                           "Passed": int(passed.sum()), "Eligible": int(passed.sum()) >= minimum})
        pairs_input.append((level, passed, temperature))
        for offset, accepted in enumerate(passed):
            seconds.append({
                "Time (s)": sample / rate + screen["matching_window_seconds"][0] + offset,
                "Block": i, "Pass": bool(accepted), **{name: values[offset] for name, values in alpha.items()},
            })

    tolerance = screen["temperature_tolerance_celsius_inclusive"]
    pairs = sum(
        int(np.count_nonzero(pass_a & pass_b & (np.abs(temp_a - temp_b) <= tolerance + 1e-9)) >= minimum)
        for (level_a, pass_a, temp_a), (level_b, pass_b, temp_b) in combinations(pairs_input, 2)
        if level_a == level_b
    )
    return HeatScreen(pd.DataFrame(block_rows), pd.DataFrame(seconds),
                      tuple(names[index] for index in omitted_indices), pairs)
