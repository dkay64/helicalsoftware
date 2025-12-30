# HeliCAL Software Suite

Modern PyQt5-based tooling for the HeliCAL additive manufacturing platform. This repository bundles the GUI control station, the pipeline helpers that voxelize/forward-project STL assets, test harnesses that mock lab hardware, and historical LEAP resources.

## Repository Overview

- `gui_test.py` – Primary application with three tabs (Pipeline, DC Motor & Encoder, G-Code) plus SSH automation to a Jetson target.
- `pipeline_helpers.py` – Headless helpers that resolve STL paths, run voxelization via `vamtoolbox`, export sinograms/montages/videos, and emit toy G-code.
- `tests/test_gui_control_station.py` – Pytest suite that mocks SSH, serial, vamtoolbox, and projector dependencies so the control station can be regression-tested on any laptop.
- `gen_toy_pipeline.py`, `translate_crop_multipass.py`, etc. – Development scripts for generating sample data.
- `LEAP/` – Vendor CT reconstruction demos and build scripts; referenced but not required to run the GUI.
- `build/`, `dist/`, `outputs/` – Generated artifacts (ignored by Git). If you produce new executables, keep them out of commits or store them with Git LFS.

## Getting Started

1. **Create an environment**
   ```bash
   conda create -n helicalsw python=3.9
   conda activate helicalsw
   ```

2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

   `requirements.txt` includes PyQt5, PySerial, Paramiko, vamtoolbox, PyTorch, matplotlib, and other packages referenced across the repo. Some LEAP demos expect CUDA-capable hardware but are optional.

3. **Run the control station**
   ```bash
   python gui_test.py
   ```

   - Demo Mode supplies packaged STL files so you can exercise the pipeline without real parts.
   - The GUI probes the Jetson via SSH on startup. Use the Connect/Disconnect buttons to manage the session manually.
   - The Pipeline tab saves projection PNGs, angle montages, toy G-code, and video previews under the chosen output folder.
   - End/stop sequences only send `M18 R T`, so the Z-axis motors stay energized even when prints are halted or the Jetson shuts down.

## Testing

All GUI behaviour is covered by pytest using extensive mocks. Tests validate:

- Pipeline parameter serialization and worker success/failure paths.
- SSH connect/disconnect workflows, password prompts, command queuing, and log routing.
- Serial RPM commands, encoder polling, jog controls, macro buttons, and G-code logging.
- Pipeline helper utilities such as sinogram previews, toy G-code generation, and reconstruction video export.

Run the suite after installing requirements:

```bash
python -m pytest tests/test_gui_control_station.py
```

No hardware is required—the suite stubs paramiko, serial, and vamtoolbox modules and feeds deterministic data into the GUI.

## Packaging / Build Artifacts

PyInstaller outputs will appear in `build/` and `dist/`. These directories are ignored; if you accidentally tracked them in a prior commit, untrack them via:

```bash
git rm -r --cached build dist
git commit -m "Remove generated binaries"
```

GitHub rejects files larger than 100 MB. Use Git LFS if you need to share installers, or distribute them outside this repository.

## Contribution Guidelines

1. Branch from `main`.
2. Make your changes and update docs/tests as needed.
3. Run `python -m pytest tests/test_gui_control_station.py`.
4. Ensure large binaries remain untracked (`git status` should not show `build/` or `dist/`).
5. Submit a pull request with a concise summary and testing notes.

Document major UI or pipeline changes in this README so future developers can ramp up quickly.
