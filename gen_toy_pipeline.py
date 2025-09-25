"""
week2_toy_pipeline.py

Purpose:
    Implements Week 2 core VAMToolbox skills:
      * Exploration of key modules (geometry, light field / projection, medium/materials)
      * Creation of simple test objects (sphere, cube)
      * Cone-beam-like projections (via tigre3D if available, with a parallel fallback)
      * Loading/voxelizing external mesh (.stl/.obj)
      * Dose accumulation simulation
      * Resin response and threshold-based development
      * Reconstruction and visualization

This version is robust against missing submodules (e.g., displaygrayscale, medium, or tigre).
"""

import os
import numpy as np

# Visualization fallback
try:
    import vamtoolbox.displaygrayscale as dgr  # preferred if present
    DISPLAY_NAME = "displaygrayscale"
except ImportError:
    try:
        import vamtoolbox.display as dgr  # fallback to generic display module
        DISPLAY_NAME = "display"
    except ImportError:
        dgr = None
        DISPLAY_NAME = None

import matplotlib.pyplot as plt  # fallback visualization

# Core VAMToolbox imports
import vamtoolbox as vam
import vamtoolbox.projector as projector_module  # for exploration
from vamtoolbox.geometry import (
    TargetGeometry,
    ProjectionGeometry,
    Sinogram,
    Reconstruction,
    Volume,
    rebinFanBeam,
)
from vamtoolbox.util.thresholding import threshold as apply_threshold

# Medium / material modeling may not be installed in all environments
try:
    from vamtoolbox.medium import IndexModel, AttenuationModel
    HAS_MEDIUM = True
except ImportError:
    IndexModel = None
    AttenuationModel = None
    HAS_MEDIUM = False

# Try to import tigre3D wrapper and ensure its dependency 'tigre' is present
TIGRE_AVAILABLE = False
try:
    from vamtoolbox.projector.tigre3D import tigre3D

    # Check if underlying 'tigre' module is importable (wrapper often depends on it)
    try:
        import tigre  # type: ignore[attr-defined]
        TIGRE_AVAILABLE = True
    except ImportError:
        print("[Info] Underlying 'tigre' library is not installed; disabling tigre3D fallback.")
        TIGRE_AVAILABLE = False
except ImportError:
    TIGRE_AVAILABLE = False

from vamtoolbox.projector import Projector3DParallel  # fallback projector


# ---------------------- Visualization helpers ---------------------- #
def fallback_show_volume(volume_array, title="Volume"):
    """Show a central slice of a 3D volume using matplotlib as fallback."""
    if volume_array.ndim == 3:
        slice_idx = volume_array.shape[2] // 2
        img = volume_array[:, :, slice_idx]
    elif volume_array.ndim == 2:
        img = volume_array
    else:
        img = np.take(volume_array, volume_array.shape[-1] // 2, axis=-1)
    plt.figure()
    plt.imshow(img, cmap="gray", origin="lower")
    plt.title(title + " (central slice)")
    plt.axis("off")
    plt.tight_layout()
    plt.show()


def fallback_show_sinogram(sino_array, title="Sinogram"):
    """Basic sinogram visualization fallback."""
    if sino_array.ndim == 3:
        mid = sino_array.shape[1] // 2
        img = sino_array[:, mid, :]
    elif sino_array.ndim == 2:
        img = sino_array
    else:
        img = np.squeeze(sino_array)
    plt.figure()
    plt.imshow(img, cmap="gray", origin="lower")
    plt.title(title)
    plt.axis("off")
    plt.tight_layout()
    plt.show()


def show_volume(title, array):
    """Unified caller for showing a volume whether display module exists or not."""
    if dgr:
        if hasattr(dgr, "showVolumeSlicer"):
            try:
                dgr.showVolumeSlicer(array, vol_type="z", title=title)
                return
            except Exception:
                pass
        if hasattr(dgr, "showVolume"):
            try:
                dgr.showVolume(array, title=title)
                return
            except Exception:
                pass
    fallback_show_volume(array, title)


def show_sinogram(title, sino_array):
    """Unified caller for showing a sinogram whether display module exists or not."""
    if dgr:
        if hasattr(dgr, "showSinoSlicer"):
            try:
                dgr.showSinoSlicer(sino_array, title=title)
                return
            except Exception:
                pass
        if hasattr(dgr, "showSino"):
            try:
                dgr.showSino(sino_array, title=title)
                return
            except Exception:
                pass
    fallback_show_sinogram(sino_array, title)


# ---------------------- Core functionality ---------------------- #
def explore_modules():
    """Print enumerated contents of key VAMToolbox modules for learning/exploration."""
    print("=== Module Exploration ===")
    print("Geometry module keys:", [k for k in dir(getattr(vam, "geometry", object())) if not k.startswith("_")][:12], "...")
    if hasattr(vam, "medium"):
        print("Medium module keys:", [k for k in dir(getattr(vam, "medium")) if not k.startswith("_")][:12], "...")
    else:
        print("Medium module not available in this installation.")
    print("Projector module keys:", [k for k in dir(projector_module) if not k.startswith("_")][:12], "...")
    if dgr:
        print(f"Display helpers from '{DISPLAY_NAME}':", [k for k in dir(dgr) if not k.startswith("_")][:12], "...")
    else:
        print("No display module available; falling back to matplotlib for visualization.")
    try:
        import vamtoolbox.util.thresholding as tt  # type: ignore
        print("Thresholding utilities:", [k for k in dir(tt) if not k.startswith("_")][:12], "...")
    except ImportError:
        print("Thresholding utilities module not found.")
    print("=== End Exploration ===\n")


def make_synthetic_object(shape: str, resolution: int = 64):
    """Generate a synthetic 3D object (sphere or cube) as a voxel volume, patched to work with ASTRA projector."""
    x = np.linspace(-1, 1, resolution)
    X, Y, Z = np.meshgrid(x, x, x, indexing="ij")

    if shape.lower() == "sphere":
        radius = 0.5
        binary = ((X ** 2 + Y ** 2 + Z ** 2) <= radius ** 2).astype(np.float32)
    elif shape.lower() == "cube":
        half = 0.5
        binary = (
            (np.abs(X) <= half)
            & (np.abs(Y) <= half)
            & (np.abs(Z) <= half)
        ).astype(np.float32)
    else:
        raise ValueError(f"Unknown shape '{shape}'")

    vol = Volume(binary, proj_geo=None)
    # Patch required attributes for parallel projector (ASTRA) compatibility
    vol.nX, vol.nY, vol.nZ = binary.shape
    vol.array = binary
    vol.voxels = binary
    return vol


def load_external_mesh(path: str, resolution: int = 64):
    """Load and voxelize an external mesh file (.stl or .obj)."""
    ext = os.path.splitext(path)[1].lower()
    if ext not in [".stl", ".obj"]:
        raise ValueError("Only .stl or .obj supported")

    if ext == ".obj":
        try:
            import trimesh
        except ImportError:
            raise RuntimeError("To load .obj you need 'trimesh' installed (pip install trimesh)")

        mesh = trimesh.load(path, force="mesh")
        tmp_stl = "temp_converted.stl"
        mesh.export(tmp_stl)
        target_geo = TargetGeometry(stlfilename=tmp_stl, resolution=resolution)
        os.remove(tmp_stl)
    else:  # .stl
        target_geo = TargetGeometry(stlfilename=path, resolution=resolution)

    return target_geo


def simulate_cone_beam_projection(target_vol: Volume, n_angles=120):
    """Simulate cone-beam-like projections and reconstruction."""
    angles = np.linspace(0, 360, n_angles, endpoint=False)
    proj_geo = ProjectionGeometry(angles, ray_type="parallel")

    # Extract the raw array for backends that expect numpy arrays
    target_array = target_vol.array if hasattr(target_vol, "array") else target_vol

    if TIGRE_AVAILABLE:
        print("Using tigre3D for cone-beam-style projection.")
        params = {
            "angles": np.deg2rad(angles),
            # Real geometry params should be populated here per tigre3D spec
        }
        try:
            # tigre3D wants the raw volume array, not the wrapped Volume object
            cone = tigre3D(target_array, params)
            projections = cone.forwardProject(target_array)
            recon_array = cone.backProject(projections)
            sinogram_obj = Volume(projections, proj_geo)
            recon_obj = Volume(recon_array, proj_geo)
            dose_volume = recon_array
            return dose_volume, sinogram_obj, recon_obj
        except Exception as e:
            print(f"[Warning] tigre3D failed ({e}); falling back.")

    print("Using parallel-beam projection fallback.")
    if hasattr(Projector3DParallel, "Projector3DParallelAstra"):
        projector = Projector3DParallel.Projector3DParallelAstra(target_geo=target_vol, proj_geo=proj_geo)
    else:
        projector = Projector3DParallel.Projector3DParallelPython(target_geo=target_vol, proj_geo=proj_geo)

    sinogram_array = projector.forward(target_array)
    sino_obj = Sinogram(sinogram_array, proj_geo)

    try:
        fan_sino = rebinFanBeam(sino_obj, vial_width=target_array.shape[0], N_screen=(128, 128), n_write=1.0, throw_ratio=1.0)
    except Exception:
        fan_sino = sino_obj

    recon_array = projector.backward(fan_sino.array if hasattr(fan_sino, "array") else fan_sino)
    recon_obj = Reconstruction(recon_array, proj_geo)
    dose_volume = recon_array
    return dose_volume, sino_obj, recon_obj



def resin_response_and_development(dose_volume, threshold=0.5):
    """Simple resin conversion and threshold-based development."""
    D0 = np.percentile(dose_volume, 75) + 1e-8
    response = 1.0 - np.exp(-dose_volume / D0)
    developed = apply_threshold(response, threshold)
    return response, developed


def visualize_all(title_prefix, target_vol, sinogram_obj, recon_obj, dose_volume, response, developed):
    """Unified visualization of pipeline outputs with fallbacks."""
    target_array = target_vol.array if hasattr(target_vol, "array") else target_vol
    sino_array = sinogram_obj.array if hasattr(sinogram_obj, "array") else sinogram_obj
    recon_array = recon_obj.array if hasattr(recon_obj, "array") else recon_obj

    show_volume(f"{title_prefix} Target", target_array)
    show_sinogram(f"{title_prefix} Sinogram", sino_array)
    show_volume(f"{title_prefix} Reconstruction (Dose)", recon_array)
    show_volume(f"{title_prefix} Resin Response", response)
    show_volume(f"{title_prefix} Developed (Thresholded)", developed)


def main():
    print("Starting Week 2 Toy Pipeline for VAMToolbox\n")
    explore_modules()

    # Synthetic objects
    for shape in ["sphere", "cube"]:
        print(f"\n--- Synthetic object: {shape} ---")
        vol = make_synthetic_object(shape, resolution=64)
        dose, sino_obj, recon_obj = simulate_cone_beam_projection(vol, n_angles=90)
        response, developed = resin_response_and_development(dose, threshold=0.5)
        visualize_all(shape.capitalize(), vol, sino_obj, recon_obj, dose, response, developed)

    # External mesh processing
    external_paths = ["ring.stl", "cube.stl"]
    for path in external_paths:
        if os.path.exists(path):
            basename = os.path.splitext(os.path.basename(path))[0]
            print(f"\n--- External mesh: {path} ---")
            try:
                target_geo = load_external_mesh(path, resolution=64)
            except Exception as e:
                print(f"Failed to load {path}: {e}")
                continue
            dose, sino_obj, recon_obj = simulate_cone_beam_projection(target_geo, n_angles=90)
            response, developed = resin_response_and_development(dose, threshold=0.5)
            visualize_all(f"External {basename}", target_geo, sino_obj, recon_obj, dose, response, developed)
        else:
            print(f"[Info] Skipping missing external mesh '{path}'.")

    # Material / medium exploration (only if available)
    print("\n--- Material / Medium Exploration ---")
    if HAS_MEDIUM:
        try:
            idx_model = IndexModel(coord_vec=np.zeros((1, 3)))  # placeholder
            att_model = AttenuationModel(coord_vec=np.zeros((1, 3)))
            print("Created placeholder IndexModel and AttenuationModel for inspection.")
        except Exception as e:
            print(f"[Warning] Material model instantiation failed: {e}")
    else:
        print("Medium module not present; skipping material modeling.")

    print("\nPipeline complete. Use the interactive windows (or fallback plots) to inspect results.")


if __name__ == "__main__":
    main()
