# Reproduce the analysis

This project tests whether changes in locally referenced C3/C4 alpha power (8–13 Hz) track differences in reported pain across temperature-matched heat repeats. The analysis uses OpenNeuro **ds008349, version 2.0.1**. Start with the [locked plan](../c3-c4-alpha-analysis-lock.json) for the cohort, screening rules, and statistical model.

## 1. Set up Python

Run these commands from the project folder. The dependency file pins the analysis, notebook, plotting, and app packages, including their transitive dependencies. The setup targets Python 3.13 on macOS and Linux. The verified environment used Python 3.13.2 on Apple silicon.

```bash
python3.13 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pip check
```

An existing project environment can use the same installation and check commands.

## 2. Download and verify the data

For the locked analysis and the publication figures, download the **59-person confirmation cohort**.

```bash
.venv/bin/python scripts/download_data.py --group confirmation
```

Other download groups serve different parts of the project.

- `--group demo` downloads one rated-heat recording for the app, about 140 MB.
- `--group pilot` downloads the original nine runs and 12 additional rated-heat runs, about 2.77 GB.
- `--group confirmation` downloads the 59 confirmation runs, about 8.28 GB.
- `--group all` downloads the complete project subset, about 11.04 GB.

The default destination is `data/raw/ds008349-2.0.1/`. The downloader verifies each file against the [pinned manifests](../data/manifests/) before accepting it. A repeated run reuses verified files and fetches missing or changed files. Completed pilot and confirmation downloads write the corresponding receipts used by the notebooks.

For an existing copy, verify the files locally.

```bash
.venv/bin/python scripts/download_data.py --group confirmation --verify-only
```

Keep the raw files in that directory. The project’s Git ignore rules cover the raw data, the Python environment, and generated analysis outputs. Cite the versioned release when using the EEG data. [OpenNeuro ds008349 v2.0.1](https://openneuro.org/datasets/ds008349/versions/2.0.1)

## 3. Rerun the locked analysis

```bash
.venv/bin/python scripts/run_analysis.py
```

This runs the locked section of [the source notebook](../confirmatory-c3-c4-alpha.ipynb) in the current Python environment and saves an executed notebook and a numeric summary in `outputs/`. The command checks the result against the reference.

- **59** recordings passed structural checks, and **44** had at least one passing block.
- **31** participants contributed **140** temperature-matched repeat comparisons.
- The estimate was **+1.62%** alpha power per 10 rating units (95% participant-bootstrap CI **−1.44% to +4.21%**, two-sided **p = 0.2624**).

To also run the contributor comparison and post hoc eye-correction analysis, add `--include-followups`. The expanded notebook and summary use the separate `confirmatory-with-followups` filename.

To work through any notebook interactively, install the project kernel and open JupyterLab.

```bash
.venv/bin/python -m ipykernel install --prefix .venv --name pain-eeg-pilot --display-name "Python (pain EEG pilot)"
.venv/bin/python -m jupyterlab
```

## 4. Regenerate the publication figures

```bash
.venv/bin/python figures/export_figure_data.py
.venv/bin/python figures/make_figures.py
```

The first command recomputes the plotting data from the locked analysis and the eye-correction follow-up. The second writes the three editable SVGs, 600 dpi PNGs, and [standalone captions](../figures/captions.txt) in `figures/`. It can also redraw the figures directly from the included plotting data.

## 5. Launch the Streamlit viewer

```bash
.venv/bin/python -m streamlit run app/app.py --server.address 127.0.0.1 --browser.gatherUsageStats false
```

Open the local URL printed in the terminal. The demo download is enough to try the viewer with a project recording. To open your own recording, upload its matching `.vhdr`, `.vmrk`, and `.eeg` files. The viewer shows raw signals, screening flags, and C3/C4 alpha power. [Viewer controls](../app/README.md)
