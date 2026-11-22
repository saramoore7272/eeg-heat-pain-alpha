"""Render the Step 13 figures as editable SVG and 600 dpi PNG."""

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.ticker import AutoMinorLocator, MultipleLocator
import numpy as np


DIRECTORY = Path(__file__).resolve().parent
BLUE = "#235B7E"
TEAL = "#1D7165"
RUST = "#9A512F"
INK = "#202C34"
MID = "#4B5C67"
GRID = "#DCE4E8"
LIGHT_BLUE = "#B5CAD7"
DPI = 600

plt.rcParams.update({
    "font.family": "DejaVu Sans",
    "font.size": 8,
    "axes.labelsize": 8,
    "axes.titlesize": 8.5,
    "axes.titleweight": "bold",
    "axes.labelcolor": INK,
    "axes.edgecolor": MID,
    "axes.linewidth": 0.65,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.unicode_minus": True,
    "xtick.labelsize": 7,
    "ytick.labelsize": 7,
    "xtick.color": MID,
    "ytick.color": MID,
    "xtick.major.size": 3,
    "ytick.major.size": 3,
    "xtick.major.width": 0.65,
    "ytick.major.width": 0.65,
    "text.color": INK,
    "grid.color": GRID,
    "grid.linewidth": 0.6,
    "legend.fontsize": 7,
    "figure.facecolor": "white",
    "axes.facecolor": "white",
    "svg.fonttype": "none",
    "svg.hashsalt": "step13-c3-c4-2026",
})


def signed(value):
    return f"{value:+.2f}".replace("-", "−")


def interval_text(result):
    return f"{signed(result['Percent CI low'])} to {signed(result['Percent CI high'])}"


def panel_heading(axis, letter, title):
    axis.set_title(f"{letter}   {title}", loc="left", pad=9)


def line_and_point(axis, result, y, color, marker="o"):
    low, high = result["Percent CI low"], result["Percent CI high"]
    axis.hlines(y, low, high, color=color, linewidth=1.5, zorder=3)
    axis.vlines([low, high], y - 0.048, y + 0.048, color=color, linewidth=1, zorder=3)
    axis.scatter(result["Percent effect"], y, s=32, marker=marker, color=color,
                 edgecolor="white", linewidth=0.5, zorder=4)


def effect_axis(axis, xlabel, zero_span=(0, 1)):
    axis.axvline(0, ymin=zero_span[0], ymax=zero_span[1], color=MID, linewidth=0.8,
                 linestyle=(0, (3, 3)), zorder=1)
    axis.set_xlim(-3, 5)
    axis.set_xticks([-2, 0, 2, 4])
    axis.xaxis.set_minor_locator(AutoMinorLocator(2))
    if zero_span == (0, 1):
        axis.grid(axis="x", zorder=0)
    axis.set_yticks([])
    axis.spines["left"].set_visible(False)
    axis.set_xlabel(xlabel)


def save(figure, name, title, description):
    figure.savefig(
        DIRECTORY / f"{name}.svg",
        metadata={"Title": title, "Description": description, "Date": None},
    )
    figure.savefig(
        DIRECTORY / f"{name}.png", dpi=DPI,
        metadata={"Title": title, "Description": description},
    )
    plt.close(figure)


def screening_figure(data):
    figure, (flow_axis, pass_axis) = plt.subplots(
        1, 2, figsize=(7.35, 3.15), gridspec_kw={"width_ratios": [1.02, 1.12]},
    )
    figure.subplots_adjust(left=0.083, right=0.975, top=0.86, bottom=0.23, wspace=0.36)
    panel_heading(flow_axis, "A", "Recording flow")
    counts = data["flow"]
    stages = [
        ("Verified recordings", counts["verified"], LIGHT_BLUE),
        ("At least one passing block", counts["passing_block"], LIGHT_BLUE),
        ("At least one matched repeat pair", counts["matched"], BLUE),
    ]
    for index, (label, value, color) in enumerate(stages):
        y = index * 0.82
        flow_axis.text(0, y - 0.19, label, va="bottom", fontsize=7.6,
                       fontweight="bold" if index == 2 else "normal")
        flow_axis.barh(y, value, height=0.24, color=color, zorder=2)
        flow_axis.text(value + 1.1, y, str(value), ha="left", va="center", fontsize=8, fontweight="bold")
    flow_axis.set(xlim=(0, 66), ylim=(2.02, -0.40), yticks=[], xlabel="Recordings (n)")
    flow_axis.set_xticks([0, 20, 40, 60])
    flow_axis.spines["left"].set_visible(False)
    flow_axis.grid(axis="x", zorder=0)

    panel_heading(pass_axis, "B", "Screening pass rates")
    rng = np.random.default_rng(834913)
    groups = [
        ("Contributed", "Contributed (n = 31)", BLUE, "o", -0.17),
        ("Did not contribute", "Did not contribute (n = 28)", RUST, "s", 0.17),
    ]
    legend_items = []
    quality = data["participant_quality"]
    for group, label, color, marker, offset in groups:
        legend_items.append(Line2D([], [], color=color, marker=marker, markersize=4.4,
                                   linestyle="none", markerfacecolor=color if marker == "o" else "white", label=label))
        for i, measure in enumerate(["Scalp seconds pass after omissions", "Eye seconds pass"]):
            values = np.array([row[measure] for row in quality if row["Group"] == group])
            y = i + offset
            jitter = rng.uniform(-0.095, 0.095, len(values))
            pass_axis.scatter(values, y + jitter, s=13, marker=marker, facecolor=color if marker == "o" else "white",
                              edgecolor=color, linewidth=0.55, alpha=0.70, zorder=2)
            pass_axis.vlines(np.median(values), y - 0.14, y + 0.14, color=color, linewidth=1.6, zorder=3)
    pass_axis.set(xlim=(-3, 103), ylim=(1.44, -0.44), yticks=[0, 1], yticklabels=["Scalp", "Eye"],
                  xlabel="Passing seconds per recording (%)")
    pass_axis.set_xticks([0, 25, 50, 75, 100])
    pass_axis.tick_params(axis="y", length=0)
    pass_axis.spines["left"].set_visible(False)
    pass_axis.grid(axis="x", zorder=0)
    figure.legend(handles=legend_items, loc="lower right", bbox_to_anchor=(0.975, 0.033), ncol=2,
                  frameon=False, handletextpad=0.40, columnspacing=1.0)
    save(figure, "figure-1-eeg-screening", "EEG screening and recording retention",
         "Recording counts and participant scalp and eye screen pass rates for the locked analysis.")


def locked_figure(data):
    figure, (scatter_axis, slope_axis) = plt.subplots(
        1, 2, figsize=(7.35, 3.05), gridspec_kw={"width_ratios": [1.37, 1.0]},
    )
    figure.subplots_adjust(left=0.103, right=0.969, top=0.87, bottom=0.202, wspace=0.33)
    panel_heading(scatter_axis, "A", "Matched block differences")
    panel_heading(slope_axis, "B", "Locked effect estimate")

    locked = data["models"][0]
    residuals = data["locked_partial_residuals"]
    x = np.array(residuals["adjusted_rating"])
    y = np.array(residuals["adjusted_log_alpha"])
    scatter_axis.axhline(0, color=GRID, linewidth=0.8, zorder=0)
    scatter_axis.axvline(0, color=GRID, linewidth=0.8, zorder=0)
    scatter_axis.scatter(x, y, s=12, color=BLUE, alpha=0.49, edgecolors="none", zorder=2)
    domain = np.array([x.min(), x.max()])
    scatter_axis.plot(domain, locked["Log effect"] * domain / 10, color=BLUE, linewidth=1.35, zorder=3)
    scatter_axis.set(xlabel="Adjusted rating difference (released units)",
                     ylabel="Adjusted log alpha difference")
    scatter_axis.xaxis.set_major_locator(MultipleLocator(50))

    effect_axis(slope_axis, "Alpha power change per 10 rating units (%)", zero_span=(0.31, 0.65))
    slope_axis.set_ylim(-0.70, 0.73)
    line_and_point(slope_axis, locked, 0, BLUE)
    slope_axis.text(0.04, 0.91, f"{signed(locked['Percent effect'])}%", transform=slope_axis.transAxes,
                    fontsize=15, fontweight="bold", color=BLUE, va="top")
    slope_axis.text(0.04, 0.77, f"95% CI {interval_text(locked)}%", transform=slope_axis.transAxes,
                    fontsize=8, color=MID, va="top")
    slope_axis.text(0.04, 0.22, f"Two-sided p = {locked['Two-sided p']:.4f}", transform=slope_axis.transAxes,
                    fontsize=7.5, va="top")
    slope_axis.text(0.04, 0.13, f"{locked['Participants']} participants · {locked['Pairs']} pairs",
                    transform=slope_axis.transAxes, fontsize=7.3, color=MID, va="top")
    save(figure, "figure-2-locked-c3-c4-alpha", "Locked association between ratings and C3/C4 alpha",
         "Adjusted matched-pair plot and the prespecified two-sided participant-bootstrap effect estimate.")


def eye_correction_figure(data):
    figure = plt.figure(figsize=(7.35, 2.55))
    grid = figure.add_gridspec(1, 3, width_ratios=[1.82, 2.65, 1.50],
                              left=0.055, right=0.98, top=0.815, bottom=0.225, wspace=0.08)
    labels, axis, numbers = [figure.add_subplot(grid[0, i]) for i in range(3)]
    for subaxis in (labels, axis, numbers):
        subaxis.set_ylim(2.48, -0.50)
    labels.set_axis_off()
    numbers.set_axis_off()
    labels.set_title("Analysis", loc="left", pad=8)
    numbers.set_title("Estimate [95% CI]", loc="left", pad=8)
    effect_axis(axis, "Alpha power change per 10 rating units (%)")

    display_names = ["Locked analysis", "Eye correction · all usable", "Eye correction · original participants"]
    for i, (result, name) in enumerate(zip(data["models"], display_names)):
        color = BLUE if i == 0 else TEAL
        labels.text(0, i - 0.08, name, va="center", fontsize=8.1, fontweight="bold" if i == 0 else "normal")
        labels.text(0, i + 0.17, f"{result['Participants']} participants · {result['Pairs']} pairs",
                    va="center", color=MID, fontsize=7)
        line_and_point(axis, result, i, color, marker="o" if i == 0 else "D")
        numbers.text(0, i - 0.09, f"{signed(result['Percent effect'])}%", va="center", fontsize=9,
                     color=color, fontweight="bold")
        numbers.text(0, i + 0.17, f"[{signed(result['Percent CI low'])}%, {signed(result['Percent CI high'])}%]",
                     va="center", color=MID, fontsize=7.3)
    save(figure, "figure-3-eye-correction-sensitivity", "Sensitivity of C3/C4 alpha association to eye correction",
         "Locked and eye-corrected estimates with 95 percent participant-bootstrap confidence intervals.")


def write_captions(data):
    counts = data["flow"]
    locked, corrected, restricted = data["models"]
    qa = data["correction_validation"]
    captions = f"""Figure 1. Recording retention and EEG screening.
(A) The locked screen retained {counts['matched']} of {counts['verified']} rated-heat recordings for the primary model. Of the {counts['verified'] - counts['matched']} noncontributing recordings, {counts['no_passing_block']} had no block with at least five passing seconds and {counts['no_matched_repeat']} had a passing block without a qualifying repeat pair. A pair required at least five common seconds at the same programmed heat level and within 0.10°C. (B) Each point is the percentage of the 90 assessed seconds per recording passing the indicated screen. Vertical marks show group medians. The scalp screen used the 0.5–150 µV peak-to-peak criterion after prespecified channel omissions. The eye screen required both filtered eye leads to remain below 100 µV peak to peak. Panels show the 59 confirmation recordings from OpenNeuro ds008349 v2.0.1, using 25–35 s after each block marker.

Figure 2. Locked C3/C4 alpha result.
(A) Each point is a matched block pair. Later-minus-earlier differences in ratings and natural-log alpha power were residualized against measured temperature differences and the heat-level-specific repeat contrast. Alpha power (8–13 Hz) was obtained from fixed local C3 and C4 references. The fitted slope gives each participant equal total weight. (B) The adjusted estimate was {signed(locked['Percent effect'])}% alpha power per 10 released rating units (95% participant-bootstrap confidence interval {interval_text(locked)}%, two-sided p = {locked['Two-sided p']:.4f}; {locked['Participants']} participants and {locked['Pairs']} pairs). The interval used {locked['Valid bootstrap draws']:,} resamples of whole participants. OpenNeuro ds008349 v2.0.1, rated heat, 25–35 s after each block marker.

Figure 3. Sensitivity to eye-artifact correction.
Points and bars are adjusted estimates and 95% participant-bootstrap confidence intervals from the same model. Slow eye-channel regression reduced median eye-aligned frontal EEG RMS from {qa['median_frontal_rms_before']:.1f} to {qa['median_frontal_rms_after']:.1f} µV in separate validation windows across {qa['validated_recordings']} validated recordings. Original passing seconds kept their original alpha values. Correction recovered matched pairs in {qa['gained_participants']} of 28 originally excluded participants. The expanded analysis estimated {signed(corrected['Percent effect'])}% per 10 rating units (95% CI {interval_text(corrected)}%, two-sided p = {corrected['Two-sided p']:.4f}; {corrected['Participants']} participants, {corrected['Pairs']} pairs). The corrected analysis restricted to the original participants estimated {signed(restricted['Percent effect'])}% (95% CI {interval_text(restricted)}%; {restricted['Participants']} participants, {restricted['Pairs']} pairs). Correction was evaluated as a post hoc sensitivity check in the same cohort. OpenNeuro ds008349 v2.0.1, rated heat, 25–35 s after each block marker.
"""
    (DIRECTORY / "captions.txt").write_text(captions, encoding="utf-8")


def main():
    data = json.loads((DIRECTORY / "c3-c4-figure-data.json").read_text(encoding="utf-8"))
    screening_figure(data)
    locked_figure(data)
    eye_correction_figure(data)
    write_captions(data)


if __name__ == "__main__":
    main()
