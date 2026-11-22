"""Export plotting data from the executed C3/C4 analysis notebook."""

from contextlib import redirect_stdout
from hashlib import sha256
import io
import json
from pathlib import Path

import nbformat
import numpy as np
import pandas as pd


PROJECT = Path(__file__).resolve().parent.parent


def source_code(notebook, first_line):
    matches = [
        cell.source for cell in notebook.cells
        if cell.cell_type == "code" and cell.source.splitlines()[0] == first_line
    ]
    if len(matches) != 1:
        raise ValueError(f"Expected one analysis cell starting with {first_line!r}")
    return matches[0]


def residual_plot_data(pairs, expected_beta):
    """Calculate partial residuals with the locked model's participant weights."""
    rating = pairs["Rating change"].to_numpy(dtype=float)
    alpha = pairs["Log alpha change"].to_numpy(dtype=float)
    nuisance = np.column_stack([
        pd.get_dummies(pairs["Repeat contrast"]).to_numpy(dtype=float),
        pairs["Temperature change"].to_numpy(dtype=float) / 0.1,
    ])
    weights = 1 / pairs.groupby("Participant")["Participant"].transform("size").to_numpy()
    root_weights = np.sqrt(weights)
    observed = np.column_stack([rating, alpha])
    fit = np.linalg.lstsq(nuisance * root_weights[:, None], observed * root_weights[:, None], rcond=None)[0]
    rating_residual, alpha_residual = (observed - nuisance @ fit).T
    beta = np.sum(weights * rating_residual * alpha_residual) / np.sum(weights * rating_residual**2) * 10
    if not np.isclose(beta, expected_beta, rtol=1e-9, atol=1e-12):
        raise ValueError("The plotted regression does not reproduce the locked slope")
    return {
        "adjusted_rating": rating_residual.tolist(),
        "adjusted_log_alpha": alpha_residual.tolist(),
    }


def json_rows(frame):
    return json.loads(frame.to_json(orient="records", double_precision=15))


def export():
    if Path.cwd() != PROJECT:
        raise SystemExit(f"Run from the project directory: {PROJECT}")
    notebook_path = PROJECT / "confirmatory-c3-c4-alpha.ipynb"
    notebook = nbformat.read(notebook_path, as_version=4)
    selected_cells = [
        "from hashlib import sha256",
        "class RecordingStructureError(ValueError):",
        "def build_pairs(recordings, eye_threshold):",
        "def fit_association(data, adjust_eye=False):",
        'contributing = set(pairs["Participant"])',
        "regression_fit_range = range(15, 25)",
        "correction_recordings, eye_validation_rows = {}, []",
        "corrected_pairs, corrected_retention = build_pairs(correction_recordings, np.inf)",
    ]
    scope = {}
    for first_line in selected_cells:
        # The executed notebook is the analysis source of truth. Skip its
        # plotting cells and suppress tables during this data-only pass.
        with redirect_stdout(io.StringIO()):
            code = source_code(notebook, first_line)
            exec(compile(code, str(notebook_path), "exec"), scope)
    compare = scope["comparison_results"]
    validation = scope["validation_passed"]
    flow = scope["flow"]
    locked = scope["primary_result"]
    if len(flow) != 59 or locked["Participants"] != 31 or locked["Pairs"] != 140:
        raise ValueError("Unexpected confirmation-cohort counts")
    if len(scope["new_contributors"]) != 19 or len(scope["corrected_pairs"]) != 312:
        raise ValueError("Unexpected eye-correction counts")

    payload = {
        "dataset": scope["plan"]["dataset"],
        "notebook": notebook_path.name,
        "notebook_sha256": sha256(notebook_path.read_bytes()).hexdigest(),
        "flow": {
            "verified": len(flow),
            "passing_block": int(flow["Blocks with at least five seconds"].gt(0).sum()),
            "matched": locked["Participants"],
            "no_passing_block": int(flow["Outcome"].eq("No block with five passing seconds").sum()),
            "no_matched_repeat": int(flow["Outcome"].eq("Passing block, no matched pair").sum()),
        },
        "participant_quality": json_rows(scope["attrition"][
            ["Group", "Scalp seconds pass after omissions", "Eye seconds pass"]
        ]),
        "locked_partial_residuals": residual_plot_data(scope["pairs"], locked["Log effect"]),
        "models": json_rows(compare),
        "correction_validation": {
            "gained_participants": len(scope["new_contributors"]),
            "validated_recordings": len(validation),
            "median_frontal_rms_before": float(validation["Frontal RMS before"].median()),
            "median_frontal_rms_after": float(validation["Frontal RMS after"].median()),
        },
    }
    path = PROJECT / "figures" / "c3-c4-figure-data.json"
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"Exported verified plotting data: {path.name}")


if __name__ == "__main__":
    export()
