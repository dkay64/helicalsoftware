# HeliCAL Software Suite

Modern PyQt5-based tooling for the HeliCAL additive manufacturing platform. The repository bundles the desktop control station, the projection/pipeline helpers, regression tests that stub all lab hardware, and legacy LEAP demos.

## Highlights

- **Single-window control station** – Pipeline, G-code, and Video Monitor tabs share one SSH connection to the Jetson target.
- **Remote automation** – Password prompts, connection indicators, and log mirroring keep the Jetson session in sync with the GUI. The prompt reappears automatically if you mistype the password.
- **Projector workflow** – Upload a local MP4, mirror playback on the Jetson (mpv with GPU acceleration + xdotool window controls), and preview the file locally.
- **Safety & convenience tools** – Set LED current via the new `M205 S###` helper, type commands directly into the console textbox, jog axes, and run canned start/end sequences.
- **Headless pipeline** – `pipeline_helpers.py` resolves STLs (demo assets included), voxelizes with `vamtoolbox`, saves sinograms/montages/G-code, and produces video previews.

## Prerequisites

### Python
- Python 3.9 (matching the lab environment) and pip.
- Install Python dependencies with `pip install -r requirements.txt`. The list covers the GUI, pipeline helpers, pytest suite, and the heavier LEAP demos (PyTorch, TIGRE, etc.).

### Remote Jetson / Linux target
- g++ toolchain plus the HeliCAL sources checked out in `~/Desktop/HeliCAL_Final`.
- [`mpv`](https://mpv.io/) and `xdotool` available on `$PATH` (used for projector playback). The GUI launches mpv with `--vo=gpu --hwdec=auto`, so make sure GPU drivers support those flags.
- Desktop session must be unlocked when you want projector playback; the GUI will remind you if the display is locked.

### Windows host
- Install a DirectShow codec pack (e.g., [K-Lite Codec Pack](https://codecguide.com/download_kl.htm)) so the Video Monitor tab can preview H.264/AAC MP4 files. Without it you’ll see `DirectShowPlayerService` errors, though uploads still succeed.

## Setup

1. **Create an environment**
   ```bash
   conda create -n vam_env python=3.9.11 vamtoolbox -c vamtoolbox -c conda-forge -c astra-toolbox
   conda activate vam_env
   ```
2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```
3. (Optional) Update `config_heliCAL.json` or Jetson credentials inside `gui_test.py` to match your lab setup.

## Running the Control Station

```bash
python gui_test.py
```

- **Connection workflow** – The GUI probes SSH automatically on launch. When you click **Connect** it prompts for the Jetson password; failed attempts immediately reprompt. Disconnecting or losing the link resets the cached state so you can reconnect without restarting the app.
- **Pipeline tab** – Choose an STL (or enable Demo Mode), configure reconstruction parameters, and run the worker thread. Outputs include `sinogram_view.png`, `reconstruction_slice.png`, `angle_montage.png`, `toy_exposure.gcode`, and `reconstruction_preview.mp4` in the selected output directory.
- **G-code tab** – Issue standard motions (`G0/G1/G4/G5/G6`), jog axes, control the projector (`M200`–`M204`), and run sequences. The LED current section sends `M205 S<value>`, while the “Console Input” textbox treats anything you type as a live G/M-code command.
- **Video Monitor tab** – Browse for an MP4 and click **Upload**. The GUI copies the file to `~/Desktop/HeliCAL_Final/Videos`, checks whether the Jetson display is unlocked, then launches mpv/xlotool commands over SSH. Playback uses GPU acceleration and the projector window is positioned automatically. The tab also plays the file locally using PyQt’s media widgets (hence the codec requirement).
- **Logging** – SSH logs appear in both the pipeline status window and the G-code console so you can correlate remote output with local commands.

## Testing

Run the pytest suite (no hardware required—the fixtures stub paramiko, serial, and vamtoolbox):

```bash
python -m pytest tests/test_gui_control_station.py
```

The tests cover pipeline configuration, SSH workflows, dialog handling, jog macros, and the helper utilities in `pipeline_helpers.py`.

## Packaging / Large Files

PyInstaller builds land in `build/` and `dist/`. These directories are ignored—if you accidentally tracked them, unstage with:

```bash
git rm -r --cached build dist
```

GitHub blocks files larger than 100 MB. Use Git LFS or another artifact channel if you need to share installers.

## Troubleshooting

- **DirectShowPlayerService errors** – Install an H.264/AAC codec pack (K-Lite) on Windows so the preview tab can render MP4s.
- **Video uploads hang at “Checking remote display”** – Unlock the Jetson desktop. The GUI polls `xset q`; if the greeter is active, mpv cannot grab a display.
- **Projector window missing/misaligned** – Ensure `mpv` and `xdotool` are installed on the Jetson and reachable on `$PATH`. Check `/tmp/mpv.log` via SSH for decoder errors.
- **SSH password mistakes** – The dialog reappears automatically. If you still cannot connect, verify network connectivity and the Wi-Fi credentials printed in the error dialog.

## Contribution Guidelines

1. Branch from `main`.
2. Implement your changes and update docs/tests accordingly.
3. Run `python -m pytest tests/test_gui_control_station.py`.
4. Confirm `git status` is clean (no generated binaries).
5. Submit a PR with a concise summary and testing notes.

Document major UI or pipeline changes here so future developers can ramp up quickly.
