import os
import numpy as np
import matplotlib.pyplot as plt

# Compatibility for older code that uses np.bool
if not hasattr(np, "bool"):
    np.bool = bool

try:
    import vamtoolbox as vam
    import vamtoolbox.projector as projector_module
    from vamtoolbox.geometry import TargetGeometry, ProjectionGeometry, Sinogram, Reconstruction
    from vamtoolbox.imagesequence import ImageConfig, ImageSeq
except Exception:
    # Import errors will be surfaced when functions are called
    vam = None
    projector_module = None
    TargetGeometry = None
    ProjectionGeometry = None
    Sinogram = None
    Reconstruction = None
    ImageConfig = None
    ImageSeq = None


def log(message: str):
    print(message)


def _sino_preview_2d(sino_array: np.ndarray) -> np.ndarray:
    arr = np.asarray(sino_array)
    if arr.ndim == 2:
        return arr  # already 2D
    if arr.ndim == 3:
        ax_sizes = arr.shape
        angles_axis = int(np.argmax(ax_sizes))
        if angles_axis != 0:
            arr = np.moveaxis(arr, angles_axis, 0)
        _, a, b = arr.shape
        if a <= b:
            img = arr[:, :, b // 2]
        else:
            img = arr[:, a // 2, :]
        return img
    arr = np.squeeze(arr)
    if arr.ndim == 2:
        return arr
    return arr[..., arr.shape[-1] // 2]


def resolve_stl_path(user_path: str | None, demo_mode: bool) -> str:
    """
    Resolve an STL path for voxelization.
    Priority:
      1) If user_path exists => use it
      2) If demo_mode => try vam.resources.load('ring.stl'), fallback to other packaged meshes
      3) If basename(user_path) is a known packaged mesh => use vam.resources.load(basename)
    """
    # 1) User-provided full/relative path
    if user_path and os.path.exists(user_path):
        log(f"Using user-selected STL file: {user_path}")
        return user_path

    # 2) Demo mode: guarantee a valid STL via packaged resource
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


def voxelize_stl(stl_path: str, resolution: int) -> 'TargetGeometry':
    log(f"Voxelizing STL: {stl_path} @ resolution={resolution}")
    if TargetGeometry is None:
        raise ImportError("vamtoolbox.geometry.TargetGeometry not available")
    tg = TargetGeometry(stlfilename=stl_path, resolution=resolution)
    return tg


def run_projection(tg: 'TargetGeometry', num_angles: int, ray_type: str) -> tuple[np.ndarray, 'Sinogram', 'Reconstruction']:
    angles = np.linspace(0, 360, num_angles, endpoint=False)
    if ProjectionGeometry is None:
        raise ImportError("vamtoolbox.geometry.ProjectionGeometry not available")
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
    if Sinogram is None:
        raise ImportError("vamtoolbox.geometry.Sinogram not available")
    sino = Sinogram(sinogram_array, proj_geo)

    # Backward: sinogram -> reconstruction (dose-ish)
    recon_array = projector.backward(sino.array)
    if Reconstruction is None:
        raise ImportError("vamtoolbox.geometry.Reconstruction not available")
    recon = Reconstruction(recon_array, proj_geo)
    return recon_array, sino, recon


def save_projection_images(output_dir: str, sino: 'Sinogram', recon_array: np.ndarray):
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


def save_angle_montage(output_dir: str, sino: 'Sinogram', n_cols: int = 10):
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


def gcode_from_slice(img: np.ndarray, cfg: dict) -> str:
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


def save_reconstruction_video(output_dir: str, sino: 'Sinogram') -> str:
    """
    Generate and save an MP4 video preview of the reconstruction.
    Returns the path to the saved video file.
    """
    if ImageConfig is None or ImageSeq is None:
        log("[WARN] Could not import vamtoolbox.imagesequence; skipping video generation")
        return ""

    try:
        log("Starting video generation...")

        # Configure image sequence parameters
        cfg = ImageConfig(
            (2560, 1600),           # Output resolution (width, height)
            intensity_scale=2,       # Brightness multiplier
            size_scale=1,           # Size scaling factor
            array_num=1,            # Number of repeated arrays
            array_offset=0,         # Spacing between arrays
            invert_v=False,         # Flip vertically or not
            v_offset=0,             # Vertical offset
            normalization_percentile=99.9,
        )

        # Convert sinogram into a sequence of projection images
        imgset = ImageSeq(cfg, sinogram=sino)
        video_path = os.path.join(output_dir, "reconstruction_preview.mp4")

        # Save as MP4 video
        imgset.saveAsVideo(
            save_path=video_path,
            rot_vel=36,      # Rotation speed (degrees per second)
            num_loops=5,     # Number of full rotations
            preview=False    # Disable GUI preview window
        )
        log(f"Saved video: {video_path}")
        return video_path

    except Exception as ve:
        log(f"[WARN] Video generation failed: {ve}")
        return ""
