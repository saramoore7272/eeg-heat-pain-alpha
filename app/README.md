# EEG recording viewer

From the project folder, run the app in the existing project environment.

```bash
.venv/bin/python -m streamlit run app/app.py --server.address 127.0.0.1 --browser.gatherUsageStats false
```

For a fresh Python 3.13 environment, follow the [project setup and data download instructions](../docs/reproduce.md). For a viewer-only installation, run `python -m pip install -r app/requirements.txt` in your virtual environment. That file uses the project’s pinned versions. Keep `c3-c4-alpha-analysis-lock.json` beside this folder.

Choose a project recording or upload the matching `.vhdr`, `.vmrk`, and `.eeg` files using their original names. The app opens project files in place. Uploaded copies are staged in a temporary directory for the session. Streamlit’s default limit is 200 MB per file.

- **Raw traces** shows the selected channels and event markers. Centering only changes how the traces are displayed.
- **Screening** shows scalp and available eye flags for each complete second in the visible window. Project rated-heat runs additionally show the locked block-by-block screen, channel omissions, and temperature-matched repeat counts.
- **C3/C4 alpha** plots 8–13 Hz power in µV² on a log scale. Filled markers pass the selected screen. The app uses the project’s local reference when the neighboring channels are available and labels acquisitions that use the original reference.

The visible-window screen is a quick quality check. The locked heat view uses the recording’s events and task channels to apply the project-specific criteria. Single-recording views describe traces, screening, and power.
