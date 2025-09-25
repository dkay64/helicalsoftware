"""
sem_test.py

Purpose:
  * Work backwards from OUTPUTS (images + G-code) without needing lab hardware.
  * Flexible: takes ANY .stl when available, OR falls back to built-in demo assets via vamtoolbox.resources.
  * Outputs:
      - Projection images (PNGs)
      - Toy G-code from a thresholded reconstruction slice
      - Status log + editable JSON config
  * Minimal GUI with "Demo Mode" toggle to guarantee a successful run off-lab.

Changes vs previous:
  - Added DEMO MODE (uses packaged demo STL, e.g., 'ring.stl', even if user path is missing)
  - Graceful file checks with helpful error messages
  - Auto-tries vam.resources.load(<basename>) when a path is missing
  - Saves an angle sweep montage PNG for impressiveness

Dependencies:
  - numpy, matplotlib, tkinter
  - vamtoolbox (ASTRA if available)

Run:
  conda activate vam_env
  python sem_test.py
"""

from __future__ import annotations
import os
import json
import time
import pathlib
import tkinter as tk
from tkinter import filedialog, messagebox
from datetime import datetime

import numpy as np
import matplotlib.pyplot as plt

# VAMToolbox imports
import vamtoolbox as vam
import vamtoolbox.projector as projector_module
from vamtoolbox.geometry import TargetGeometry, ProjectionGeometry, Sinogram, Reconstruction

# ---------------------------------- Config ---------------------------------- #
DEFAULT_CONFIG = {
    "resolution": 96,            # voxel grid side (cubic)
    "num_angles": 120,           # number of projection angles (0..360)
    "ray_type": "parallel",    # 'parallel' (fallback) until cone-beam path is confirmed
    "proj_threshold": 0.5,       # 0..1, for toy gcode ON/OFF decision
    "pixel_size_mm": 0.1,        # for G-code scaling (assume square pixels)
    "feedrate": 1200,            # mm/min (placeholder)
    "laser_power_on": 255,       # 0..255 PWM (placeholder)
    "laser_power_off": 0,        # 0..255
    "dwell_ms": 2,               # per pixel dwell (simple timing placeholder)
}

CONFIG_PATH = "config_heliCAL.json"
LOG_PATH = "run_status.log"

# --------------------------------- Logging ---------------------------------- #
def log(msg: str):
    """Append a timestamped line to the status log and print to console."""
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def load_config() -> dict:
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
                for k, v in DEFAULT_CONFIG.items():
                    cfg.setdefault(k, v)
                return cfg
        except Exception as e:
            log(f"[WARN] Failed to read config: {e}; using defaults.")
    return DEFAULT_CONFIG.copy()


def save_config(cfg: dict):
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
        log("Saved config_heliCAL.json")
    except Exception as e:
        log(f"[ERROR] Failed to save config: {e}")

# ------------------------------ Core Pipeline ------------------------------- #






def _sino_preview_2d(sino_array: np.ndarray) -> np.ndarray:
    """
    Convert sinogram of shape:
      - (angles, det_u, det_v)  -> take central det_v slice -> (angles, det_u)
      - (det_u, angles, det_v)  -> move axes, then slice
      - (angles, det) or (det, angles) -> return as-is (2D)
    into a 2D image suitable for imshow.
    """
    arr = np.asarray(sino_array)
    if arr.ndim == 2:
        return arr  # already 2D

    if arr.ndim == 3:
        # Heuristics: we want (angles, detector) for display.
        # Identify the 'angles' axis as the one that matches num_angles best.
        # Fallback: assume axis 0 is angles.
        ax_sizes = arr.shape
        # Try to find a plausible angles axis by the one closest to the max dimension.
        angles_axis = int(np.argmax(ax_sizes))
        if angles_axis != 0:
            arr = np.moveaxis(arr, angles_axis, 0)  # (angles, ?, ?)

        # Now arr is (angles, A, B). Take central slice of the smallest detector dim.
        _, a, b = arr.shape
        if a <= b:
            img = arr[:, :, b // 2]  # (angles, A)
        else:
            img = arr[:, a // 2, :]  # (angles, B)

        return img

    # Fallback: squeeze and try again (handles odd shapes)
    arr = np.squeeze(arr)
    if arr.ndim == 2:
        return arr
    # Last resort: pick a middle slice across last axis
    return arr[..., arr.shape[-1] // 2]


def resolve_stl_path(user_path: str | None, demo_mode: bool) -> str:
    """
    Resolve an STL path for voxelization.
    Priority:
      1) If demo_mode => try vam.resources.load('ring.stl'), fallback to other packaged meshes
      2) If user_path exists => use it
      3) If basename(user_path) is a known packaged mesh => use vam.resources.load(basename)
    """
    # 1) Demo mode: guarantee a valid STL via packaged resource
    if demo_mode:
        for name in ("ring.stl", "cube.stl", "trifurcatedvasculature.stl"):
            try:
                p = vam.resources.load(name)
                log(f"[DEMO] Using packaged resource: {name}")
                return p
            except Exception:
                continue
        raise FileNotFoundError("Demo assets not found in vamtoolbox resources.")

    # 2) User-provided full/relative path
    if user_path and os.path.exists(user_path):
        return user_path

    # 3) User typed a bare filename: try packaged assets by basename
    if user_path:
        base = os.path.basename(user_path)
        try:
            p = vam.resources.load(base)
            log(f"[Fallback] Using packaged resource for '{base}'.")
            return p
        except Exception:
            pass

    raise FileNotFoundError(
        "Input .stl file does not exist. Use Browse to pick a real file or enable Demo Mode.")


def voxelize_stl(stl_path: str, resolution: int) -> TargetGeometry:
    log(f"Voxelizing STL: {stl_path} @ resolution={resolution}")
    tg = TargetGeometry(stlfilename=stl_path, resolution=resolution)
    return tg


def run_projection(tg: TargetGeometry, num_angles: int, ray_type: str) -> tuple[np.ndarray, Sinogram, Reconstruction]:
    angles = np.linspace(0, 360, num_angles, endpoint=False)
    proj_geo = ProjectionGeometry(angles, ray_type=ray_type)

    # Prefer ASTRA projector; fall back to Python implementation if needed
    try:
        projector = projector_module.Projector3DParallel.Projector3DParallelAstra(
            target_geo=tg, proj_geo=proj_geo
        )
        log("Using Projector3DParallelAstra backend.")
    except Exception as e:
        log(f"[WARN] ASTRA projector unavailable ({e}); trying Python fallback.")
        projector = projector_module.Projector3DParallel.Projector3DParallelPython(
            target_geo=tg, proj_geo=proj_geo
        )
        log("Using Projector3DParallelPython backend.")

    # Forward: volume -> sinogram
    sinogram_array = projector.forward(tg.array)
    sino = Sinogram(sinogram_array, proj_geo)

    # Backward: sinogram -> reconstruction (dose-ish)
    recon_array = projector.backward(sino.array)
    recon = Reconstruction(recon_array, proj_geo)
    return recon_array, sino, recon


def save_projection_images(output_dir: str, sino: Sinogram, recon_array: np.ndarray):
    os.makedirs(output_dir, exist_ok=True)

    # --- Sinogram preview (always 2D) ---
    sino_img = _sino_preview_2d(sino.array)
    plt.figure()
    plt.imshow(sino_img, cmap="gray", origin="lower", aspect="auto")
    plt.title("Sinogram (preview)")
    plt.axis("off")
    sino_path = os.path.join(output_dir, "sinogram_view.png")
    plt.savefig(sino_path, bbox_inches="tight", dpi=220)
    plt.close()
    log(f"Saved {sino_path}")

    # --- Reconstruction central slice (2D) ---
    rec = np.asarray(recon_array)
    if rec.ndim >= 3:
        mid = rec.shape[2] // 2
        rec2d = rec[:, :, mid]
    elif rec.ndim == 2:
        rec2d = rec
    else:
        rec2d = np.squeeze(rec)
        if rec2d.ndim != 2:
            # pick a slice along last axis if still not 2D
            rec2d = rec[..., rec.shape[-1] // 2]

    plt.figure()
    plt.imshow(rec2d, cmap="gray", origin="lower")
    plt.title("Reconstruction (central slice)")
    plt.axis("off")
    recon_path = os.path.join(output_dir, "reconstruction_slice.png")
    plt.savefig(recon_path, bbox_inches="tight", dpi=220)
    plt.close()
    log(f"Saved {recon_path}")

    return sino_path, recon_path


def save_angle_montage(output_dir: str, sino: Sinogram, n_cols: int = 10):
    """
    Save a montage sampling multiple angles.
    Works for 2D (angles × det) and 3D (angles × det_u × det_v) sinograms.
    """
    os.makedirs(output_dir, exist_ok=True)
    data = np.asarray(sino.array)

    # Ensure angles is axis 0
    if data.ndim == 2:
        # (angles, det) or (det, angles)
        if data.shape[0] >= data.shape[1]:
            angles_first = data
        else:
            angles_first = data.T
        frames = [angles_first[i:i+1, :] for i in range(angles_first.shape[0])]
        # Turn each row into a thin image
        frames = [np.repeat(f, repeats=8, axis=0) for f in frames]  # make it more visible
    elif data.ndim == 3:
        # Move angles to axis 0
        angles_axis = int(np.argmax(data.shape))
        if angles_axis != 0:
            data = np.moveaxis(data, angles_axis, 0)  # (angles, det_u, det_v)
        A, U, V = data.shape
        mid_v = V // 2
        frames = [data[i, :, mid_v] for i in range(A)]  # each is (det_u,)
        # Expand to 2D small strips for display
        frames = [np.repeat(f[np.newaxis, :], repeats=8, axis=0) for f in frames]
    else:
        data = np.squeeze(data)
        if data.ndim == 2:
            return save_angle_montage(output_dir, Sinogram(data, sino.proj_geo), n_cols=n_cols)
        # give up gracefully
        log("[WARN] Could not generate montage: unexpected sinogram shape.")
        return

    # Pick up to 20 frames evenly
    n = len(frames)
    if n == 0:
        log("[WARN] Empty sinogram; skipping montage.")
        return
    import math
    take = min(n, 20)
    idxs = np.linspace(0, n - 1, take, dtype=int)

    n_rows = math.ceil(take / n_cols)
    fig, axes = plt.subplots(n_rows, n_cols, figsize=(1.8*n_cols, 1.8*n_rows))
    axes = np.atleast_2d(axes)
    for k, ax in enumerate(axes.ravel()):
        ax.axis("off")
        if k < take:
            ax.imshow(frames[idxs[k]], cmap="gray", origin="lower", aspect="auto")
            ax.set_title(f"θ {idxs[k]}")
    fig.suptitle("Angle Sweep Montage", fontsize=12)
    fig.tight_layout()
    out = os.path.join(output_dir, "angle_montage.png")
    fig.savefig(out, dpi=200)
    plt.close(fig)
    log(f"Saved {out}")


# ------------------------------ Toy G-code ---------------------------------- #

def gcode_from_slice(img: np.ndarray, cfg: dict) -> str:
    """
    Convert a 2D grayscale image (0..1) into a toy raster G-code.
    Strategy:
      - Scanlines along X, step along Y.
      - If pixel >= threshold => laser/pump ON, else OFF.
      - Scale pixels by pixel_size_mm.
    """
    thr = float(cfg["proj_threshold"])  # 0..1
    px = float(cfg["pixel_size_mm"])    # mm/pixel
    fr = int(cfg["feedrate"])          # mm/min
    p_on = int(cfg["laser_power_on"])  # PWM
    p_off = int(cfg["laser_power_off"])# PWM
    dwell_ms = int(cfg["dwell_ms"])    # ms

    h, w = img.shape

    lines = [
        ";; --- HeliCAL Toy G-code (raster) ---",
        ";; Units: mm | Feed: mm/min | Power: PWM 0..255",
        "G21 ; set units to mm",
        "G90 ; absolute positioning",
        f"F{fr}",
    ]

    y = 0.0
    for r in range(h):
        x = 0.0
        cols = range(w) if r % 2 == 0 else range(w - 1, -1, -1)  # serpentine
        lines.append(f"; Row {r}")
        lines.append(f"G0 X{0.0:.3f} Y{y:.3f}")
        last_on = False
        for c in cols:
            val = float(img[r, c])
            want_on = (val >= thr)
            gx = x
            if want_on != last_on:
                p = p_on if want_on else p_off
                lines.append(f"M3 S{p}")
                last_on = want_on
            lines.append(f"G1 X{gx:.3f} Y{y:.3f}")
            if want_on and dwell_ms > 0:
                lines.append(f"G4 P{dwell_ms}")
            x += px if r % 2 == 0 else -px
        lines.append("M3 S0")
        y += px

    lines += ["M5", "G0 X0 Y0", ";; --- End Toy G-code ---"]
    return "\n".join(lines)


def write_gcode_from_recon_slice(output_dir: str, recon_array: np.ndarray, cfg: dict):
    os.makedirs(output_dir, exist_ok=True)
    mid = recon_array.shape[2] // 2 if recon_array.ndim == 3 else 0
    sl = recon_array[:, :, mid] if recon_array.ndim == 3 else recon_array
    sl = sl.astype(np.float32)
    sl -= sl.min()
    if sl.max() > 0:
        sl /= sl.max()
    code = gcode_from_slice(sl, cfg)
    out_path = os.path.join(output_dir, "toy_exposure.gcode")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(code)
    log(f"Saved {out_path}")
    return out_path


# ----------------------------------- GUI ------------------------------------ #
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("HeliCAL STL → Images → Toy G-code")
        self.geometry("820x580")
        self.cfg = load_config()
        self.stl_path = tk.StringVar(value="")
        self.out_dir = tk.StringVar(value=str(pathlib.Path.cwd() / "outputs"))
        self.demo_mode = tk.BooleanVar(value=True)  # default ON for remote demo
        self._build_ui()

    def _build_ui(self):
        pad = {"padx": 8, "pady": 6}
        row = 0
        tk.Label(self, text="STL File:").grid(row=row, column=0, sticky="e", **pad)
        tk.Entry(self, textvariable=self.stl_path, width=60).grid(row=row, column=1, **pad)
        tk.Button(self, text="Browse", command=self.pick_stl).grid(row=row, column=2, **pad)

        row += 1
        tk.Checkbutton(self, text="Demo Mode (use packaged ring/cube if file missing)",
                       variable=self.demo_mode).grid(row=row, column=1, sticky="w", **pad)

        row += 1
        tk.Label(self, text="Output Dir:").grid(row=row, column=0, sticky="e", **pad)
        tk.Entry(self, textvariable=self.out_dir, width=60).grid(row=row, column=1, **pad)
        tk.Button(self, text="Browse", command=self.pick_outdir).grid(row=row, column=2, **pad)

        # Parameters
        row += 1
        tk.Label(self, text="Resolution (vox)").grid(row=row, column=0, sticky="e", **pad)
        self.e_res = tk.Entry(self, width=12); self.e_res.insert(0, str(self.cfg["resolution"]))
        self.e_res.grid(row=row, column=1, sticky="w", **pad)

        row += 1
        tk.Label(self, text="# Angles").grid(row=row, column=0, sticky="e", **pad)
        self.e_ang = tk.Entry(self, width=12); self.e_ang.insert(0, str(self.cfg["num_angles"]))
        self.e_ang.grid(row=row, column=1, sticky="w", **pad)

        row += 1
        tk.Label(self, text="Threshold (0..1)").grid(row=row, column=0, sticky="e", **pad)
        self.e_thr = tk.Entry(self, width=12); self.e_thr.insert(0, str(self.cfg["proj_threshold"]))
        self.e_thr.grid(row=row, column=1, sticky="w", **pad)

        row += 1
        tk.Label(self, text="Pixel size (mm)").grid(row=row, column=0, sticky="e", **pad)
        self.e_px = tk.Entry(self, width=12); self.e_px.insert(0, str(self.cfg["pixel_size_mm"]))
        self.e_px.grid(row=row, column=1, sticky="w", **pad)

        row += 1
        tk.Label(self, text="Feedrate (mm/min)").grid(row=row, column=0, sticky="e", **pad)
        self.e_fr = tk.Entry(self, width=12); self.e_fr.insert(0, str(self.cfg["feedrate"]))
        self.e_fr.grid(row=row, column=1, sticky="w", **pad)

        row += 1
        tk.Label(self, text="Laser ON PWM (0..255)").grid(row=row, column=0, sticky="e", **pad)
        self.e_on = tk.Entry(self, width=12); self.e_on.insert(0, str(self.cfg["laser_power_on"]))
        self.e_on.grid(row=row, column=1, sticky="w", **pad)

        row += 1
        tk.Label(self, text="Laser OFF PWM (0..255)").grid(row=row, column=0, sticky="e", **pad)
        self.e_off = tk.Entry(self, width=12); self.e_off.insert(0, str(self.cfg["laser_power_off"]))
        self.e_off.grid(row=row, column=1, sticky="w", **pad)

        row += 1
        tk.Label(self, text="Dwell per px (ms)").grid(row=row, column=0, sticky="e", **pad)
        self.e_dw = tk.Entry(self, width=12); self.e_dw.insert(0, str(self.cfg["dwell_ms"]))
        self.e_dw.grid(row=row, column=1, sticky="w", **pad)

        # Action buttons
        row += 1
        tk.Button(self, text="Run Pipeline", command=self.run_pipeline).grid(row=row, column=1, sticky="w", **pad)
        tk.Button(self, text="Save Config", command=self.save_cfg_clicked).grid(row=row, column=2, sticky="w", **pad)

        # Status box
        row += 1
        tk.Label(self, text="Status Log:").grid(row=row, column=0, sticky="ne", **pad)
        self.txt = tk.Text(self, height=12, width=92)
        self.txt.grid(row=row, column=1, columnspan=2, sticky="w", **pad)
        self.after(300, self._tail_log_periodic)

    def pick_stl(self):
        path = filedialog.askopenfilename(title="Choose STL", filetypes=[("STL files", "*.stl"), ("All", "*.*")])
        if path:
            self.stl_path.set(path)

    def pick_outdir(self):
        d = filedialog.askdirectory(title="Choose output directory")
        if d:
            self.out_dir.set(d)

    def save_cfg_clicked(self):
        self._refresh_cfg_from_ui()
        save_config(self.cfg)
        messagebox.showinfo("Saved", "Configuration saved.")

    def _refresh_cfg_from_ui(self):
        self.cfg["resolution"] = int(self.e_res.get())
        self.cfg["num_angles"] = int(self.e_ang.get())
        self.cfg["proj_threshold"] = float(self.e_thr.get())
        self.cfg["pixel_size_mm"] = float(self.e_px.get())
        self.cfg["feedrate"] = int(self.e_fr.get())
        self.cfg["laser_power_on"] = int(self.e_on.get())
        self.cfg["laser_power_off"] = int(self.e_off.get())
        self.cfg["dwell_ms"] = int(self.e_dw.get())

    def _tail_log_periodic(self):
        try:
            if os.path.exists(LOG_PATH):
                with open(LOG_PATH, "r", encoding="utf-8") as f:
                    content = f.read()[-6000:]
                self.txt.delete("1.0", tk.END)
                self.txt.insert(tk.END, content)
        except Exception:
            pass
        self.after(600, self._tail_log_periodic)

    def run_pipeline(self):
        stl = self.stl_path.get().strip()
        out_dir = self.out_dir.get().strip()
        os.makedirs(out_dir, exist_ok=True)

        self._refresh_cfg_from_ui()
        save_config(self.cfg)

        try:
            start = time.time()
            # Resolve STL (demo or real)
            resolved = resolve_stl_path(stl if stl else None, self.demo_mode.get())
            log(f"=== Run start: STL='{resolved}' (demo={self.demo_mode.get()}) ===")

            tg = voxelize_stl(resolved, self.cfg["resolution"])
            recon_array, sino, recon = run_projection(tg, self.cfg["num_angles"], ray_type=self.cfg.get("ray_type", "parallel"))
            spath, rpath = save_projection_images(out_dir, sino, recon_array)
            save_angle_montage(out_dir, sino, n_cols=10)
            gpath = write_gcode_from_recon_slice(out_dir, recon_array, self.cfg)
            elapsed = time.time() - start
            log(f"=== Run done in {elapsed:.1f}s ===")
            messagebox.showinfo("Done", f"Saved:\n{spath}\n{rpath}\n{os.path.join(out_dir, 'angle_montage.png')}\n{gpath}")
        except FileNotFoundError as fnf:
            log(f"[ERROR] {fnf}")
            messagebox.showerror("File not found", str(fnf))
        except Exception as e:
            log(f"[ERROR] Pipeline failed: {e}")
            messagebox.showerror("Error", str(e))


if __name__ == "__main__":
    # touch log file to start
    with open(LOG_PATH, "a", encoding="utf-8") as _f:
        _f.write("")
    app = App()
    app.mainloop()