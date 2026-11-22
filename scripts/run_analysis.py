"""Execute the locked analysis without editing the source notebook."""

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

from jupyter_client.kernelspec import KernelSpecManager
from jupyter_client.manager import AsyncKernelManager
from nbclient import NotebookClient
import nbformat


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "confirmatory-c3-c4-alpha.ipynb"
RECEIPT = ROOT / "data/raw/ds008349-2.0.1/confirmation-heat-download-manifest.json"
LOCK_SHA = "37716ce8fc908cfe245b3426d9f6d2aff4ad54bba9fe5da3a6432a5e54c40eee"
FOLLOWUP_HEADING = "## Follow-up · Who contributed to the confirmation test?"


def validate_reference(summary):
    expected_counts = {"Downloaded": 59, "Structurally valid": 59, "Has passing block": 44,
                       "Contributes": 31, "Pairs": 140, "Matched pair-seconds": 980}
    values = {"Percent effect": 1.6167190983, "Percent CI low": -1.443973438,
              "Percent CI high": 4.2132622858, "Two-sided p": 0.2624}
    return (
        summary["coverage"] == expected_counts
        and summary["primary"]["Valid bootstrap draws"] == 9999
        and all(math.isclose(summary["primary"][key], value, rel_tol=0,
                             abs_tol=0.0002 if key == "Two-sided p" else 0.00005)
                for key, value in values.items())
    )


def execute(notebook):
    # Use the Python running this command, regardless of existing Jupyter kernels
    # or the user's system Python. The kernel is temporary.
    kernel_name = "pain-eeg-pilot"
    with TemporaryDirectory(prefix="eeg-analysis-kernel-") as directory:
        kernel_path = Path(directory) / kernel_name
        kernel_path.mkdir()
        spec = {
            "argv": [sys.executable, "-m", "ipykernel_launcher", "-f", "{connection_file}"],
            "display_name": "EEG project Python", "language": "python",
            "env": {"OPENBLAS_NUM_THREADS": "1", "VECLIB_MAXIMUM_THREADS": "1", "OMP_NUM_THREADS": "1"},
        }
        (kernel_path / "kernel.json").write_text(json.dumps(spec), encoding="utf-8")
        specs = KernelSpecManager(kernel_dirs=[directory], ensure_native_kernel=False)
        manager = AsyncKernelManager(kernel_name=kernel_name, kernel_spec_manager=specs)
        client = NotebookClient(
            notebook, km=manager, timeout=300,
            resources={"metadata": {"path": str(ROOT)}},
        )
        client.execute(cleanup_kc=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--include-followups", action="store_true",
                        help="Also rerun the contributor comparison and eye-correction sensitivity analysis.")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "outputs")
    args = parser.parse_args()
    if not RECEIPT.is_file():
        parser.exit(1, "Download the confirmation data first: python scripts/download_data.py --group confirmation\n")
    if hashlib.sha256((ROOT / "c3-c4-alpha-analysis-lock.json").read_bytes()).hexdigest() != LOCK_SHA:
        parser.exit(1, "The source analysis lock differs from the verified project lock.\n")

    notebook = nbformat.read(SOURCE, as_version=4)
    if not args.include_followups:
        positions = [i for i, cell in enumerate(notebook.cells)
                     if cell.cell_type == "markdown" and cell.source.splitlines()[0] == FOLLOWUP_HEADING]
        if len(positions) != 1:
            parser.exit(1, "Could not locate the boundary between the locked analysis and follow-ups.\n")
        notebook.cells = notebook.cells[:positions[0]]

    notebook.cells.append(nbformat.v4.new_code_cell(
        'print(json.dumps({"coverage": primary_coverage, "primary": primary_result}))'
    ))
    execute(notebook)
    summary = json.loads(notebook.cells.pop().outputs[0].text)
    summary["source_notebook"] = SOURCE.name
    summary["analysis_lock_sha256"] = LOCK_SHA
    summary["matches_reference"] = validate_reference(summary)

    out = args.output_dir.resolve()
    out.mkdir(parents=True, exist_ok=True)
    stem = "confirmatory-with-followups" if args.include_followups else "confirmatory-locked"
    notebook_path = out / f"{stem}.ipynb"
    summary_path = out / f"{stem}-summary.json"
    nbformat.validate(notebook)
    with TemporaryDirectory(dir=out, prefix="eeg-analysis-output-") as temporary:
        stage = Path(temporary)
        nbformat.write(notebook, stage / notebook_path.name)
        (stage / summary_path.name).write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        (stage / notebook_path.name).replace(notebook_path)
        (stage / summary_path.name).replace(summary_path)

    result = summary["primary"]
    print(f"{result['Participants']} participants, {result['Pairs']} matched pairs.")
    print(f"{result['Percent effect']:+.2f}% alpha power per 10 rating units "
          f"(95% CI {result['Percent CI low']:+.2f}% to {result['Percent CI high']:+.2f}%; "
          f"two-sided p = {result['Two-sided p']:.4f}).")
    print(f"Executed notebook: {notebook_path}")
    print(f"Numeric summary: {summary_path}")
    if not summary["matches_reference"]:
        parser.exit(1, "Results differ from the verified reference. Inspect the saved outputs.\n")
    print("Results match the verified reference.")


if __name__ == "__main__":
    main()
