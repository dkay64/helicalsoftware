import sys
import os
import json
import math
import time
import subprocess
import threading
from dataclasses import dataclass, asdict
from typing import Optional, Tuple, Dict, Any

import cv2
import numpy as np
import serial

from PyQt5.QtCore import QTimer, Qt, QThread, pyqtSignal
from PyQt5.QtGui import QImage, QPixmap, QFont
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QTabWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QFileDialog, QLabel, QLineEdit, QTextEdit, QMessageBox,
    QListWidget, QListWidgetItem, QGroupBox, QFormLayout, QDoubleSpinBox,
    QCheckBox, QSplitter, QProgressBar
)


# ==============================================================================
# Calibration Data Model & Step Definitions
# ==============================================================================
@dataclass
class CalibrationData:
    vial_diameter_mm: float = 25.0
    vial_height_mm: float = 60.0
    angle_offset_deg: float = 0.0
    r_focus_mm: float = 186.0
    r_focus_score: float = 0.0
    tilt_top_clarity: float = 0.0
    tilt_bottom_clarity: float = 0.0
    mm_per_px: float = 0.0
    r_coupling_dx_dy: Tuple[float, float] = (0.0, 0.0)
    t_coupling_dx_dy: Tuple[float, float] = (0.0, 0.0)
    z_coupling_dx_dy: Tuple[float, float] = (0.0, 0.0)
    centricity_offset_mm: Tuple[float, float] = (0.0, 0.0)


CALIBRATION_STEPS = [
    {
        "id": "setup",
        "title": "0. Initial Setup & Homing",
        "mode": "Automated + Input",
        "goal": (
            "Turn projector ON (M200), project horizontal centerline, record resin vial "
            "dimensions, and home all axes (G28) to center starting positions."
        ),
        "tolerance": "Limit switches triggered; vial dimensions confirmed."
    },
    {
        "id": "angle",
        "title": "1. Angle Calibration (0R_0Z)",
        "mode": "Automated CV",
        "goal": (
            "Project 1-px line in T-Z plane, sweep R to verify uniform width, and measure "
            "line slope to determine projector angular rotation offset."
        ),
        "tolerance": "|Angle Offset| <= 0.25 deg"
    },
    {
        "id": "r_focus",
        "title": "2. R-Axis Focus (186 mm ± 2 mm)",
        "mode": "Automated Sweep",
        "goal": (
            "Project 15x15 px square and scan R across 184.0–188.0 mm in 0.05 mm steps. "
            "Accept best position meeting 'close-enough' sharpness threshold."
        ),
        "tolerance": "R in [184.0, 188.0] mm & Normalized Clarity >= Threshold"
    },
    {
        "id": "tilt",
        "title": "3. Projector Tilt / Rotation (Manual)",
        "mode": "Manual Physical Adjustment",
        "goal": (
            "Project top and bottom squares. Physically adjust projector tilt/rotation "
            "while comparing Initial (left) vs. Current (right) top/bottom ROI clarity."
        ),
        "tolerance": "|Top Clarity - Bottom Clarity| <= 0.10 (Operator Confirmed)"
    },
    {
        "id": "r_cal",
        "title": "4. R-Axis Scale & Coupling (R_TZ)",
        "mode": "Automated CV",
        "goal": (
            "Project center + outer radial patterns in 1 mm increments, measure pixel "
            "displacement (dx, dy), and compute mm/px scaling and R coupling."
        ),
        "tolerance": "Linear fit R^2 >= 0.98 across radial steps"
    },
    {
        "id": "t_cal",
        "title": "5. T-Axis Coupling (T_RZ)",
        "mode": "Automated CV",
        "goal": (
            "Project center square, jog T across known positions, refocus R within "
            "tolerance, record (dx, dy) & R/Z coupling, then return T to 0."
        ),
        "tolerance": "Refocus clarity >= Threshold; T returned to 0"
    },
    {
        "id": "z_cal",
        "title": "6. Z-Axis Coupling (Z_RT)",
        "mode": "Automated CV",
        "goal": (
            "Project center square, jog Z by known height step, refocus R within "
            "tolerance, record (dx, dy) & R/T coupling, then return Z to 0."
        ),
        "tolerance": "Refocus clarity >= Threshold; Z returned to 0"
    },
    {
        "id": "centricity",
        "title": "7. Centricity Calibration",
        "mode": "Automated CV + Stage 180°",
        "goal": (
            "Home (G28), center R/T on projected dot, rotate stage 180°, measure centroid "
            "offset, and halve R/T displacement until within tolerance."
        ),
        "tolerance": "Centroid offset <= 3 px (~0.01 mm)"
    },
]


# ==============================================================================
# Hardware & Pattern Bridge (Connects GUI to master_queue / Camera / Simulator)
# ==============================================================================
class CalibrationHardwareBridge:
    """
    Encapsulates G-code motion, projector pattern selection, and frame capture.
    Supports live hardware (master_queue / OpenCV) and a built-in simulator.
    """
    # Soft bounds from HeliCAL SOP0001
    Z_BOUNDS = (0, 90000)
    T_BOUNDS = (-645288, 0)
    R_BOUNDS = (-330000, 0)

    # Microstep resolution (0.9375 um = 0.0009375 mm/step)
    MM_PER_MICROSTEP = 0.0009375

    def __init__(self, camera_getter, simulation_mode: bool = True):
        self.get_camera = camera_getter
        self.simulation_mode = simulation_mode
        self.master_proc: Optional[subprocess.Popen] = None
        self.sim_r_mm = 188.0
        self.sim_t_mm = 0.0
        self.sim_z_mm = 0.0
        self.sim_theta_deg = 0.0
        self.current_pattern = "centerline"

    def send_gcode(self, cmd: str) -> str:
        cmd = cmd.strip()
        if self.simulation_mode:
            time.sleep(0.03)
            return f"[SIM GCODE] {cmd}"

        if self.master_proc and self.master_proc.stdin:
            try:
                self.master_proc.stdin.write((cmd + "\n").encode("utf-8"))
                self.master_proc.stdin.flush()
                return f"[SENT] {cmd}"
            except Exception as e:
                return f"[GCODE ERR] {cmd}: {e}"
        return f"[NO MASTER_QUEUE PIPE] {cmd}"

    def set_projector_pattern(self, pattern_name: str) -> str:
        self.current_pattern = pattern_name
        if self.simulation_mode:
            return f"[SIM PROJECTOR] Pattern -> {pattern_name}"
        return f"[PROJECTOR] Pattern -> {pattern_name}"

    def move_r_mm(self, target_r_mm: float) -> str:
        self.sim_r_mm = target_r_mm
        steps = -int(round(target_r_mm / self.MM_PER_MICROSTEP))
        steps = max(self.R_BOUNDS[0], min(self.R_BOUNDS[1], steps))
        return self.send_gcode(f"G90\nG0 R{steps}")

    def jog_t_mm(self, delta_t_mm: float) -> str:
        self.sim_t_mm += delta_t_mm
        steps = int(round(delta_t_mm / self.MM_PER_MICROSTEP))
        return self.send_gcode(f"G91\nG0 T{steps}")

    def jog_z_mm(self, delta_z_mm: float) -> str:
        self.sim_z_mm += delta_z_mm
        steps = int(round(delta_z_mm / self.MM_PER_MICROSTEP))
        return self.send_gcode(f"G91\nG0 Z{steps}")

    def rotate_stage_deg(self, delta_deg: float) -> str:
        self.sim_theta_deg = (self.sim_theta_deg + delta_deg) % 360.0
        return self.send_gcode(f"G91\nG0 A{delta_deg:.2f}")

    def grab_frame(self) -> np.ndarray:
        cam = self.get_camera()
        if not self.simulation_mode and cam is not None and cam.isOpened():
            ret, frame = cam.read()
            if ret and frame is not None:
                return frame

        # --- Synthetic Metrology Frame for Off-Hardware Testing ---
        h, w = 480, 640
        img = np.zeros((h, w, 3), dtype=np.uint8)
        cx, cy = w // 2, h // 2

        # Defocus blur proportional to distance from true focus (185.75 mm)
        defocus = abs(self.sim_r_mm - 185.75)
        ksize = int(min(31, max(1, round(defocus * 8) * 2 + 1)))

        if self.current_pattern == "centerline":
            angle_rad = math.radians(0.18)
            dx = int(200 * math.sin(angle_rad))
            cv2.line(img, (cx - dx, 40), (cx + dx, h - 40), (255, 255, 255), 2)
        elif self.current_pattern == "center_square":
            sx = int(cx + self.sim_t_mm * 18 + (18 if self.sim_theta_deg >= 179 else 0))
            sy = int(cy - self.sim_z_mm * 18 - (14 if self.sim_theta_deg >= 179 else 0))
            cv2.rectangle(img, (sx - 14, sy - 14), (sx + 14, sy + 14), (255, 255, 255), -1)
        elif self.current_pattern == "top_bottom_squares":
            cv2.rectangle(img, (cx - 14, 50), (cx + 14, 78), (255, 255, 255), -1)
            cv2.rectangle(img, (cx - 14, h - 78), (cx + 14, h - 50), (255, 255, 255), -1)
        elif self.current_pattern == "radial_dots":
            cv2.circle(img, (cx, cy), 6, (255, 255, 255), -1)
            offset_px = int(45 + (self.sim_r_mm - 184.0) * 18)
            cv2.circle(img, (cx + offset_px, cy - 4), 6, (255, 255, 255), -1)

        if ksize > 1:
            img = cv2.GaussianBlur(img, (ksize, ksize), 0)

        noise = np.random.normal(0, 3, img.shape).astype(np.int16)
        img = np.clip(img.astype(np.int16) + noise, 0, 255).astype(np.uint8)
        return img


# ==============================================================================
# Computer Vision Analysis Helpers
# ==============================================================================
class CalibrationCV:
    @staticmethod
    def compute_sharpness(gray: np.ndarray, roi: Optional[Tuple[int, int, int, int]] = None) -> float:
        if roi is not None:
            x, y, w, h = roi
            gray = gray[y:y + h, x:x + w]
        if gray.size == 0:
            return 0.0
        lap_var = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        return float(min(1.0, lap_var / 600.0))

    @staticmethod
    def measure_line_angle(frame: np.ndarray, tag: str = "") -> Tuple[float, np.ndarray]:
        vis = frame.copy()
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        _, thresh = cv2.threshold(gray, 80, 255, cv2.THRESH_BINARY)
        pts = cv2.findNonZero(thresh)
        angle_deg = 0.0
        if pts is not None and len(pts) > 10:
            [vx, vy, x0, y0] = cv2.fitLine(pts, cv2.DIST_L2, 0, 0.01, 0.01)
            angle_deg = math.degrees(math.atan2(float(vx[0]), float(vy[0])))
            if angle_deg > 90:
                angle_deg -= 180
            elif angle_deg < -90:
                angle_deg += 180
            h = frame.shape[0]
            t1 = int((0 - y0[0]) / (vy[0] + 1e-6))
            t2 = int((h - y0[0]) / (vy[0] + 1e-6))
            p1 = (int(x0[0] + t1 * vx[0]), 0)
            p2 = (int(x0[0] + t2 * vx[0]), h)
            cv2.line(vis, p1, p2, (0, 255, 0), 2)
        prefix = f"{tag}: " if tag else ""
        cv2.putText(vis, f"{prefix}Angle {angle_deg:+.3f} deg", (15, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
        return angle_deg, vis

    @staticmethod
    def find_brightest_centroid(frame: np.ndarray, tag: str = "") -> Tuple[Tuple[float, float], np.ndarray]:
        vis = frame.copy()
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        _, thresh = cv2.threshold(gray, 100, 255, cv2.THRESH_BINARY)
        m = cv2.moments(thresh)
        h, w = gray.shape
        cx, cy = w / 2.0, h / 2.0
        if m["m00"] > 0:
            cx = m["m10"] / m["m00"]
            cy = m["m01"] / m["m00"]
        cv2.drawMarker(vis, (w // 2, h // 2), (255, 200, 0), cv2.MARKER_CROSS, 24, 2)
        cv2.circle(vis, (int(round(cx)), int(round(cy))), 8, (0, 255, 0), 2)
        prefix = f"{tag}: " if tag else ""
        cv2.putText(vis, f"{prefix}({cx:.1f}, {cy:.1f}) px", (15, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.68, (0, 255, 0), 2)
        return (cx, cy), vis


# ==============================================================================
# Worker Thread for Non-Blocking Automated Step Execution
# ==============================================================================
class CalibrationStepWorker(QThread):
    log_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(int)
    initial_image_signal = pyqtSignal(np.ndarray)
    image_signal = pyqtSignal(np.ndarray)
    step_completed = pyqtSignal(str, bool, str, dict)

    def __init__(
        self,
        step_id: str,
        bridge: CalibrationHardwareBridge,
        cal_data: CalibrationData,
        r_center_mm: float = 186.0,
        r_tol_mm: float = 2.0,
        r_step_mm: float = 0.05,
        focus_threshold: float = 0.85,
        initial_baseline: Optional[Dict[str, Any]] = None,
    ):
        super().__init__()
        self.step_id = step_id
        self.bridge = bridge
        self.cal_data = cal_data
        self.r_center_mm = r_center_mm
        self.r_tol_mm = r_tol_mm
        self.r_step_mm = r_step_mm
        self.focus_threshold = focus_threshold
        self.initial_baseline = initial_baseline if initial_baseline is not None else {}
        self._abort = False

    def abort(self):
        self._abort = True

    def run(self):
        try:
            if self.step_id == "setup":
                self._run_setup()
            elif self.step_id == "angle":
                self._run_angle()
            elif self.step_id == "r_focus":
                self._run_r_focus()
            elif self.step_id == "tilt":
                self._run_tilt_check()
            elif self.step_id == "r_cal":
                self._run_r_cal()
            elif self.step_id == "t_cal":
                self._run_t_cal()
            elif self.step_id == "z_cal":
                self._run_z_cal()
            elif self.step_id == "centricity":
                self._run_centricity()
        except Exception as e:
            self.log_signal.emit(f"[ERROR] {e}")
            self.step_completed.emit(self.step_id, False, f"Error: {e}", {})

    def _run_setup(self):
        self.progress_signal.emit(15)
        self.log_signal.emit(self.bridge.send_gcode("M200"))  # Projector ON
        self.log_signal.emit(self.bridge.set_projector_pattern("centerline"))

        init_frame = self.bridge.grab_frame()
        h, w = init_frame.shape[:2]
        (ix, _), _ = CalibrationCV.find_brightest_centroid(init_frame)
        init_err = abs(ix - (w / 2.0))
        ref_err = self.initial_baseline.setdefault("init_err", init_err)

        cv2.putText(init_frame, f"INITIAL: Center Err={ref_err:.2f} px", (15, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 165, 255), 2)
        self.initial_image_signal.emit(init_frame)

        self.progress_signal.emit(50)
        self.log_signal.emit(self.bridge.send_gcode("G28"))   # Home axes
        self.log_signal.emit(self.bridge.move_r_mm(self.r_center_mm))

        cal_frame = self.bridge.grab_frame()
        (cx, _), _ = CalibrationCV.find_brightest_centroid(cal_frame)
        cal_err = abs(cx - (w / 2.0))
        improved = cal_err <= ref_err

        cv2.putText(
            cal_frame,
            f"CURRENT: Center Err={cal_err:.2f} px (Init {ref_err:.2f})",
            (15, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.62,
            (0, 255, 0) if improved else (0, 0, 255), 2
        )
        self.image_signal.emit(cal_frame)
        self.progress_signal.emit(100)

        if improved:
            self.step_completed.emit(
                "setup", True,
                f"Setup improved alignment ({ref_err:.2f} -> {cal_err:.2f} px); updated R={self.r_center_mm:.1f} mm.",
                {"r_focus_mm": self.r_center_mm}
            )
        else:
            self.step_completed.emit(
                "setup", False,
                f"Not updated: center offset {cal_err:.2f} px > initial {ref_err:.2f} px (no improvement).",
                {}
            )

    def _run_angle(self):
        self.progress_signal.emit(20)
        self.log_signal.emit(self.bridge.set_projector_pattern("centerline"))
        time.sleep(0.08)
        f0 = self.bridge.grab_frame()
        init_deg, init_vis = CalibrationCV.measure_line_angle(f0, tag="INITIAL")
        ref_deg = self.initial_baseline.setdefault("init_deg", init_deg)
        self.initial_image_signal.emit(init_vis)

        time.sleep(0.08)
        f1 = self.bridge.grab_frame()
        angle_deg, cal_vis = CalibrationCV.measure_line_angle(f1, tag="CURRENT")
        self.image_signal.emit(cal_vis)
        self.progress_signal.emit(100)

        # Only update if |new_angle| < |initial_angle|
        improved = abs(angle_deg) < abs(ref_deg)
        if improved:
            passed = abs(angle_deg) <= 0.25
            msg = (
                f"Angle improved (|{ref_deg:+.3f}°| -> |{angle_deg:+.3f}°|); updated angle offset = {angle_deg:+.3f}°."
                if passed else
                f"Angle improved (|{ref_deg:+.3f}°| -> |{angle_deg:+.3f}°|), but still > 0.25°. Rotate mount by {-angle_deg:+.3f}°."
            )
            self.step_completed.emit("angle", passed, msg, {"angle_offset_deg": angle_deg})
        else:
            msg = (
                f"Not updated: |{angle_deg:+.3f}°| >= initial |{ref_deg:+.3f}°| "
                f"(no improvement; kept {self.cal_data.angle_offset_deg:+.3f}°)."
            )
            self.step_completed.emit("angle", False, msg, {})

    def _run_r_focus(self):
        self.log_signal.emit(self.bridge.set_projector_pattern("center_square"))
        orig_r = self.cal_data.r_focus_mm
        r_start = self.r_center_mm + self.r_tol_mm
        r_end = self.r_center_mm - self.r_tol_mm
        n_steps = max(1, int(round((r_start - r_end) / self.r_step_mm)))

        # Capture Initial (Uncalibrated) frame at the start of the sweep
        self.bridge.move_r_mm(r_start)
        init_frame = self.bridge.grab_frame()
        init_gray = cv2.cvtColor(init_frame, cv2.COLOR_BGR2GRAY)
        h, w = init_gray.shape
        roi = (w // 2 - 60, h // 2 - 60, 120, 120)
        init_score = CalibrationCV.compute_sharpness(init_gray, roi)
        ref_score = self.initial_baseline.setdefault("init_score", init_score)

        init_vis = init_frame.copy()
        cv2.rectangle(init_vis, (roi[0], roi[1]), (roi[0] + roi[2], roi[1] + roi[3]), (0, 165, 255), 2)
        cv2.putText(init_vis, f"INITIAL: R={r_start:.2f} mm | Sharpness={ref_score:.2f}",
                    (15, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (0, 165, 255), 2)
        self.initial_image_signal.emit(init_vis)

        best_r = self.r_center_mm
        best_score = -1.0
        best_vis = None

        for i in range(n_steps + 1):
            if self._abort:
                return
            r_pos = r_start - i * self.r_step_mm
            self.bridge.move_r_mm(r_pos)
            frame = self.bridge.grab_frame()
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            score = CalibrationCV.compute_sharpness(gray, roi)

            vis = frame.copy()
            color = (0, 255, 0) if score >= self.focus_threshold else (0, 165, 255)
            cv2.rectangle(vis, (roi[0], roi[1]), (roi[0] + roi[2], roi[1] + roi[3]), color, 2)
            cv2.putText(
                vis,
                f"CURRENT: R={r_pos:.2f} mm | Sharpness={score:.2f} (Init {ref_score:.2f})",
                (15, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.58, color, 2
            )
            self.image_signal.emit(vis)
            self.progress_signal.emit(int(100 * (i + 1) / (n_steps + 1)))

            if score > best_score:
                best_score = score
                best_r = r_pos
                best_vis = vis.copy()
                cv2.putText(
                    best_vis,
                    f"Delta Sharpness: {best_score - ref_score:+.2f}",
                    (15, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (0, 255, 0), 2
                )

        improved = best_score > ref_score
        if improved:
            self.bridge.move_r_mm(best_r)
            if best_vis is not None:
                self.image_signal.emit(best_vis)
            passed = best_score >= self.focus_threshold
            msg = (
                f"Focus improved ({ref_score:.2f} -> {best_score:.2f}); updated R = {best_r:.2f} mm."
                if passed else
                f"Focus improved ({ref_score:.2f} -> {best_score:.2f}) at R = {best_r:.2f} mm, but below {self.focus_threshold:.2f}."
            )
            self.step_completed.emit("r_focus", passed, msg, {"r_focus_mm": best_r, "r_focus_score": best_score})
        else:
            self.bridge.move_r_mm(orig_r)
            msg = f"Not updated: sharpness {best_score:.2f} <= initial {ref_score:.2f} (kept R = {orig_r:.2f} mm)."
            self.step_completed.emit("r_focus", False, msg, {})

    def _run_tilt_check(self):
        self.log_signal.emit(self.bridge.set_projector_pattern("top_bottom_squares"))
        frame = self.bridge.grab_frame()
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        h, w = gray.shape
        top_roi = (w // 2 - 60, 25, 120, 80)
        bot_roi = (w // 2 - 60, h - 105, 120, 80)

        top_score = CalibrationCV.compute_sharpness(gray, top_roi)
        bot_score = CalibrationCV.compute_sharpness(gray, bot_roi)
        diff = abs(top_score - bot_score)

        first_run = "init_diff" not in self.initial_baseline
        ref_diff = self.initial_baseline.setdefault("init_diff", diff)

        init_vis = frame.copy()
        cv2.rectangle(init_vis, (top_roi[0], top_roi[1]), (top_roi[0] + top_roi[2], top_roi[1] + top_roi[3]), (0, 165, 255), 2)
        cv2.rectangle(init_vis, (bot_roi[0], bot_roi[1]), (bot_roi[0] + bot_roi[2], bot_roi[1] + bot_roi[3]), (0, 165, 255), 2)
        cv2.putText(init_vis, f"INITIAL: Top={top_score:.2f} | Bot={bot_score:.2f} | Diff={ref_diff:.2f}",
                    (15, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.56, (0, 165, 255), 2)
        self.initial_image_signal.emit(init_vis)

        has_prior = (self.cal_data.tilt_top_clarity > 0.0) or (self.cal_data.tilt_bottom_clarity > 0.0)
        improved = (diff < ref_diff) or (first_run and not has_prior and diff <= 0.10)

        cur_vis = frame.copy()
        box_color = (0, 255, 0) if improved else (0, 0, 255)
        cv2.rectangle(cur_vis, (top_roi[0], top_roi[1]), (top_roi[0] + top_roi[2], top_roi[1] + top_roi[3]), box_color, 2)
        cv2.rectangle(cur_vis, (bot_roi[0], bot_roi[1]), (bot_roi[0] + bot_roi[2], bot_roi[1] + bot_roi[3]), box_color, 2)
        cv2.putText(cur_vis, f"CURRENT: Top={top_score:.2f} | Bot={bot_score:.2f} | Diff={diff:.2f} (Init {ref_diff:.2f})",
                    (15, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.54, box_color, 2)
        self.image_signal.emit(cur_vis)
        self.progress_signal.emit(100)

        if improved:
            passed = diff <= 0.10
            msg = (
                f"Tilt updated: Top={top_score:.2f}, Bot={bot_score:.2f} (Diff={diff:.2f} <= 0.10)."
                if passed else
                f"Tilt improved (Diff {ref_diff:.2f} -> {diff:.2f}), still > 0.10. Adjust tilt further and re-run."
            )
            self.step_completed.emit(
                "tilt", passed, msg,
                {"tilt_top_clarity": top_score, "tilt_bottom_clarity": bot_score}
            )
        else:
            msg = f"Not updated: tilt diff {diff:.2f} >= initial {ref_diff:.2f} (no improvement)."
            self.step_completed.emit("tilt", False, msg, {})

    def _run_r_cal(self):
        self.log_signal.emit(self.bridge.set_projector_pattern("radial_dots"))
        displacements = []
        for idx, r_sep in enumerate([1.0, 2.0, 3.0]):
            self.bridge.move_r_mm(self.cal_data.r_focus_mm + r_sep)
            frame = self.bridge.grab_frame()
            tag = "INITIAL (+1mm)" if idx == 0 else f"STEP (+{r_sep:.0f}mm)"
            (cx, cy), vis = CalibrationCV.find_brightest_centroid(frame, tag=tag)
            displacements.append((r_sep, cx, cy))
            if idx == 0:
                self.initial_image_signal.emit(vis)
            self.image_signal.emit(vis)
            self.progress_signal.emit(int(100 * (idx + 1) / 3))

        self.bridge.move_r_mm(self.cal_data.r_focus_mm)
        dx = displacements[-1][1] - displacements[0][1]
        dy = displacements[-1][2] - displacements[0][2]
        px_dist = math.hypot(dx, dy)
        mm_per_px = (2.0 / px_dist) if px_dist > 1e-3 else 0.00345

        mid_x = 0.5 * (displacements[0][1] + displacements[-1][1])
        mid_y = 0.5 * (displacements[0][2] + displacements[-1][2])
        cal_err_px = math.hypot(displacements[1][1] - mid_x, displacements[1][2] - mid_y)
        prev_scale = self.cal_data.mm_per_px if self.cal_data.mm_per_px > 0 else 0.00345
        init_err_px = abs((2.0 / prev_scale) - px_dist)
        ref_err_px = self.initial_baseline.setdefault("init_err_px", init_err_px)

        improved = (px_dist > 1e-3) and (cal_err_px < ref_err_px)
        if improved:
            msg = (
                f"R-axis scale improved error ({ref_err_px:.2f} -> {cal_err_px:.2f} px); "
                f"updated scale = {mm_per_px:.5f} mm/px | (dx, dy) = ({dx:.2f}, {dy:.2f}) px."
            )
            self.step_completed.emit(
                "r_cal", True, msg,
                {"mm_per_px": mm_per_px, "r_coupling_dx_dy": (dx, dy)}
            )
        else:
            msg = (
                f"Not updated: R-axis scale residual {cal_err_px:.2f} px >= initial {ref_err_px:.2f} px "
                f"(kept {self.cal_data.mm_per_px:.5f} mm/px)."
            )
            self.step_completed.emit("r_cal", False, msg, {})

    def _run_t_cal(self):
        self.log_signal.emit(self.bridge.set_projector_pattern("center_square"))
        f0 = self.bridge.grab_frame()
        (x0, y0), init_vis = CalibrationCV.find_brightest_centroid(f0, tag="INITIAL T=0")
        self.initial_image_signal.emit(init_vis)
        self.progress_signal.emit(35)

        self.log_signal.emit(self.bridge.jog_t_mm(5.0))
        f1 = self.bridge.grab_frame()
        (x1, y1), vis = CalibrationCV.find_brightest_centroid(f1, tag="JOGGED T+5mm")
        cv2.line(vis, (int(x0), int(y0)), (int(x1), int(y1)), (0, 255, 255), 2)
        self.image_signal.emit(vis)
        self.progress_signal.emit(70)

        self.log_signal.emit(self.bridge.jog_t_mm(-5.0))  # Return T to 0
        f_ret = self.bridge.grab_frame()
        (x_ret, y_ret), _ = CalibrationCV.find_brightest_centroid(f_ret)
        self.progress_signal.emit(100)

        jog_shift_px = math.hypot(x1 - x0, y1 - y0)
        ret_err_px = math.hypot(x_ret - x0, y_ret - y0)
        prev_best_err = self.initial_baseline.get("best_ret_err", float("inf"))

        improved = (jog_shift_px > 1.0) and (ret_err_px < jog_shift_px) and (ret_err_px < prev_best_err)
        if improved:
            self.initial_baseline["best_ret_err"] = ret_err_px
            dx, dy = (x1 - x0) / 5.0, (y1 - y0) / 5.0
            msg = f"T-axis coupling updated = ({dx:.2f}, {dy:.2f}) px/mm (return err {ret_err_px:.2f} < shift {jog_shift_px:.2f} px)."
            self.step_completed.emit("t_cal", True, msg, {"t_coupling_dx_dy": (dx, dy)})
        else:
            msg = (
                f"Not updated: T-axis return error ({ret_err_px:.2f} px) did not improve over "
                f"initial/previous ({min(jog_shift_px, prev_best_err):.2f} px)."
            )
            self.step_completed.emit("t_cal", False, msg, {})

    def _run_z_cal(self):
        self.log_signal.emit(self.bridge.set_projector_pattern("center_square"))
        f0 = self.bridge.grab_frame()
        (x0, y0), init_vis = CalibrationCV.find_brightest_centroid(f0, tag="INITIAL Z=0")
        self.initial_image_signal.emit(init_vis)
        self.progress_signal.emit(35)

        self.log_signal.emit(self.bridge.jog_z_mm(5.0))
        f1 = self.bridge.grab_frame()
        (x1, y1), vis = CalibrationCV.find_brightest_centroid(f1, tag="JOGGED Z+5mm")
        cv2.line(vis, (int(x0), int(y0)), (int(x1), int(y1)), (255, 0, 255), 2)
        self.image_signal.emit(vis)
        self.progress_signal.emit(70)

        self.log_signal.emit(self.bridge.jog_z_mm(-5.0))  # Return Z to 0
        f_ret = self.bridge.grab_frame()
        (x_ret, y_ret), _ = CalibrationCV.find_brightest_centroid(f_ret)
        self.progress_signal.emit(100)

        jog_shift_px = math.hypot(x1 - x0, y1 - y0)
        ret_err_px = math.hypot(x_ret - x0, y_ret - y0)
        prev_best_err = self.initial_baseline.get("best_ret_err", float("inf"))

        improved = (jog_shift_px > 1.0) and (ret_err_px < jog_shift_px) and (ret_err_px < prev_best_err)
        if improved:
            self.initial_baseline["best_ret_err"] = ret_err_px
            dx, dy = (x1 - x0) / 5.0, (y1 - y0) / 5.0
            msg = f"Z-axis coupling updated = ({dx:.2f}, {dy:.2f}) px/mm (return err {ret_err_px:.2f} < shift {jog_shift_px:.2f} px)."
            self.step_completed.emit("z_cal", True, msg, {"z_coupling_dx_dy": (dx, dy)})
        else:
            msg = (
                f"Not updated: Z-axis return error ({ret_err_px:.2f} px) did not improve over "
                f"initial/previous ({min(jog_shift_px, prev_best_err):.2f} px)."
            )
            self.step_completed.emit("z_cal", False, msg, {})

    def _run_centricity(self):
        self.log_signal.emit(self.bridge.set_projector_pattern("center_square"))
        self.log_signal.emit(self.bridge.send_gcode("G28"))
        f0 = self.bridge.grab_frame()
        h, w = f0.shape[:2]
        (x0, y0), init_vis = CalibrationCV.find_brightest_centroid(f0, tag="INITIAL 0 deg")
        self.initial_image_signal.emit(init_vis)
        self.progress_signal.emit(35)

        self.log_signal.emit(self.bridge.rotate_stage_deg(180.0))
        f180 = self.bridge.grab_frame()
        (x180, y180), _ = CalibrationCV.find_brightest_centroid(f180)
        self.progress_signal.emit(70)

        scale = self.cal_data.mm_per_px if self.cal_data.mm_per_px > 0 else 0.00345
        ecc_r_mm = 0.5 * (x180 - x0) * scale
        ecc_t_mm = 0.5 * (y180 - y0) * scale
        init_err_px = 0.5 * math.hypot(x180 - x0, y180 - y0)
        ref_err_px = self.initial_baseline.setdefault("init_err_px", init_err_px)

        self.log_signal.emit(self.bridge.move_r_mm(self.cal_data.r_focus_mm - ecc_r_mm))
        self.log_signal.emit(self.bridge.jog_t_mm(-ecc_t_mm))
        f_cal = self.bridge.grab_frame()
        (x_cal, y_cal), vis = CalibrationCV.find_brightest_centroid(f_cal, tag="CORRECTED 180 deg")
        cv2.line(vis, (int(x0), int(y0)), (int(x_cal), int(y_cal)), (0, 0, 255), 2)
        self.image_signal.emit(vis)
        self.progress_signal.emit(100)

        cal_err_px = math.hypot(x_cal - (w / 2.0), y_cal - (h / 2.0))
        improved = cal_err_px < ref_err_px

        if improved:
            passed = cal_err_px <= 3.0
            msg = (
                f"Centricity improved ({ref_err_px:.1f} -> {cal_err_px:.1f} px); "
                f"updated offset (R, T) = ({ecc_r_mm:+.4f}, {ecc_t_mm:+.4f}) mm."
            )
            self.step_completed.emit(
                "centricity", passed, msg,
                {"centricity_offset_mm": (ecc_r_mm, ecc_t_mm)}
            )
        else:
            self.log_signal.emit(self.bridge.move_r_mm(self.cal_data.r_focus_mm))
            self.log_signal.emit(self.bridge.jog_t_mm(ecc_t_mm))
            msg = (
                f"Not updated: residual offset {cal_err_px:.1f} px >= initial {ref_err_px:.1f} px "
                f"(no improvement)."
            )
            self.step_completed.emit("centricity", False, msg, {})


# ==============================================================================
# Main HeliCAL Control Panel GUI
# ==============================================================================
class HeliCALGui(QMainWindow):
    """
    Main GUI for the HeliCAL Control Panel.
    """
    def __init__(self):
        super().__init__()
        self.setWindowTitle("HeliCAL Automated Alignment GUI")
        self.resize(1320, 780)

        # Placeholders for serial & camera
        self.serial_port = None
        self.camera = None

        # Runtime-configurable counts per theta revolution
        self.counts_per_theta_rev = 245426  # editable in UI

        # Automated Calibration State
        self.cal_data = CalibrationData()
        self.current_step_idx = 0
        self.step_status: Dict[str, str] = {s["id"]: "Pending" for s in CALIBRATION_STEPS}
        self.cal_worker: Optional[CalibrationStepWorker] = None
        self.initial_frame_locked = False
        self.initial_baseline: Dict[str, Any] = {}
        self.last_annotated_frame: Optional[np.ndarray] = None
        self.show_live_feed = True

        self.bridge = CalibrationHardwareBridge(
            camera_getter=lambda: self.camera,
            simulation_mode=True
        )

        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)

        self._build_calibration_tab()
        self._build_rotation_tab()
        self._build_print_tab()
        self._build_balance_tab()
        self._build_camera_tab()

        # Timer for live camera frames
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_frame)

        self._refresh_step_ui()

    # ---------------- Automated Calibration Tab ----------------
    def _build_calibration_tab(self):
        tab = QWidget()
        root_layout = QHBoxLayout()

        # Left Panel: Step List & Hardware/Tolerance Parameters
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_panel.setMaximumWidth(330)

        left_layout.addWidget(QLabel("<b>Calibration Sequence</b>"))
        self.step_list = QListWidget()
        for step in CALIBRATION_STEPS:
            self.step_list.addItem(QListWidgetItem(f"[Pending] {step['title']}"))
        self.step_list.currentRowChanged.connect(self._on_step_selected)
        left_layout.addWidget(self.step_list)

        # Setup & Focus Tolerance Group
        param_group = QGroupBox("Setup & 'Close-Enough' Focus Window")
        form = QFormLayout()

        self.chk_sim_mode = QCheckBox("Simulation Mode (No Hardware)")
        self.chk_sim_mode.setChecked(True)
        self.chk_sim_mode.toggled.connect(self._toggle_sim_mode)
        form.addRow(self.chk_sim_mode)

        self.spin_vial_diam = QDoubleSpinBox()
        self.spin_vial_diam.setRange(5.0, 150.0)
        self.spin_vial_diam.setValue(25.0)
        self.spin_vial_diam.setSuffix(" mm")
        form.addRow("Vial Diameter:", self.spin_vial_diam)

        self.spin_vial_height = QDoubleSpinBox()
        self.spin_vial_height.setRange(10.0, 250.0)
        self.spin_vial_height.setValue(60.0)
        self.spin_vial_height.setSuffix(" mm")
        form.addRow("Vial Height:", self.spin_vial_height)

        self.spin_r_center = QDoubleSpinBox()
        self.spin_r_center.setRange(50.0, 254.0)
        self.spin_r_center.setValue(186.0)
        self.spin_r_center.setSuffix(" mm")
        form.addRow("Nominal R Focus:", self.spin_r_center)

        self.spin_r_tol = QDoubleSpinBox()
        self.spin_r_tol.setRange(0.2, 20.0)
        self.spin_r_tol.setValue(2.0)
        self.spin_r_tol.setSuffix(" mm")
        form.addRow("Focus Search ±Range:", self.spin_r_tol)

        self.spin_focus_thresh = QDoubleSpinBox()
        self.spin_focus_thresh.setRange(0.10, 0.99)
        self.spin_focus_thresh.setSingleStep(0.05)
        self.spin_focus_thresh.setValue(0.85)
        form.addRow("Min Sharpness Score:", self.spin_focus_thresh)

        param_group.setLayout(form)
        left_layout.addWidget(param_group)

        btn_save_cal = QPushButton("Save Calibration JSON (config_heliCAL.json)")
        btn_save_cal.clicked.connect(self.save_calibration_json)
        left_layout.addWidget(btn_save_cal)

        # Right Panel: Active Step Banner, Side-by-Side Comparison Views, Controls & Log
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)

        # Step Banner
        step_box = QGroupBox("Current Calibration Step")
        step_box_layout = QVBoxLayout()
        self.lbl_step_title = QLabel()
        title_font = QFont()
        title_font.setPointSize(12)
        title_font.setBold(True)
        self.lbl_step_title.setFont(title_font)

        self.lbl_step_goal = QLabel()
        self.lbl_step_goal.setWordWrap(True)
        self.lbl_step_tol = QLabel()
        self.lbl_step_tol.setStyleSheet("color: #2b5b84; font-weight: bold;")

        self.lbl_prompt_banner = QLabel("Ready to run step.")
        self.lbl_prompt_banner.setWordWrap(True)
        self.lbl_prompt_banner.setStyleSheet(
            "background-color: #eef5ff; border: 1px solid #99c2ff; padding: 8px; border-radius: 4px;"
        )

        self.step_progress = QProgressBar()
        self.step_progress.setValue(0)

        step_box_layout.addWidget(self.lbl_step_title)
        step_box_layout.addWidget(self.lbl_step_goal)
        step_box_layout.addWidget(self.lbl_step_tol)
        step_box_layout.addWidget(self.lbl_prompt_banner)
        step_box_layout.addWidget(self.step_progress)
        step_box.setLayout(step_box_layout)
        right_layout.addWidget(step_box)

        # Action Buttons Row
        btn_row = QHBoxLayout()
        self.btn_run_step = QPushButton("▶ Run Current Step")
        self.btn_run_step.setStyleSheet("font-weight: bold; padding: 8px;")
        self.btn_run_step.clicked.connect(self.run_current_calibration_step)

        self.btn_reset_initial = QPushButton("Reset Initial Snapshot")
        self.btn_reset_initial.clicked.connect(self.reset_initial_snapshot)

        self.btn_toggle_view = QPushButton("Right View: Live Feed (Click for Snapshot)")
        self.btn_toggle_view.clicked.connect(self.toggle_cal_camera_view)

        self.btn_next_step = QPushButton("Confirm && Move to Next Step ->")
        self.btn_next_step.setStyleSheet("font-weight: bold; padding: 8px;")
        self.btn_next_step.clicked.connect(self.advance_to_next_step)

        btn_row.addWidget(self.btn_run_step)
        btn_row.addWidget(self.btn_reset_initial)
        btn_row.addWidget(self.btn_toggle_view)
        btn_row.addWidget(self.btn_next_step)
        right_layout.addLayout(btn_row)

        # Side-by-Side Image Comparison + Log Splitter
        splitter = QSplitter(Qt.Vertical)

        comparison_container = QWidget()
        comparison_layout = QHBoxLayout(comparison_container)
        comparison_layout.setContentsMargins(0, 0, 0, 0)

        # Left Image Box: Initial (Before)
        init_group = QGroupBox("1. Initial Image (Before Calibration)")
        init_box_layout = QVBoxLayout(init_group)
        self.lbl_cal_initial = QLabel("Initial image will appear here when step starts")
        self.lbl_cal_initial.setAlignment(Qt.AlignCenter)
        self.lbl_cal_initial.setMinimumSize(360, 260)
        self.lbl_cal_initial.setStyleSheet("background-color: #111; color: #bbb; border: 1px solid #555;")
        init_box_layout.addWidget(self.lbl_cal_initial)

        # Right Image Box: Calibrated / Current (After)
        cal_group = QGroupBox("2. Current / Calibrated Image (After Changes)")
        cal_box_layout = QVBoxLayout(cal_group)
        self.lbl_cal_calibrated = QLabel("Live / Calibrated image will appear here")
        self.lbl_cal_calibrated.setAlignment(Qt.AlignCenter)
        self.lbl_cal_calibrated.setMinimumSize(360, 260)
        self.lbl_cal_calibrated.setStyleSheet("background-color: #111; color: #ddd; border: 1px solid #555;")
        cal_box_layout.addWidget(self.lbl_cal_calibrated)

        comparison_layout.addWidget(init_group, stretch=1)
        comparison_layout.addWidget(cal_group, stretch=1)
        splitter.addWidget(comparison_container)

        self.cal_log = QTextEdit()
        self.cal_log.setReadOnly(True)
        self.cal_log.setMaximumHeight(140)
        splitter.addWidget(self.cal_log)

        right_layout.addWidget(splitter, stretch=1)

        root_layout.addWidget(left_panel)
        root_layout.addWidget(right_panel, stretch=1)
        tab.setLayout(root_layout)
        self.tabs.addTab(tab, "Calibration (Auto)")

    # ---------------- Rotation / Print / Balance / Camera Tabs ----------------
    def _build_rotation_tab(self):
        tab = QWidget()
        layout = QVBoxLayout()

        hbox1 = QHBoxLayout()
        self.port_input = QLineEdit("/dev/ttyTHS1")
        btn_connect = QPushButton("Connect ESP32")
        btn_connect.clicked.connect(self.connect_esp32)
        hbox1.addWidget(QLabel("Serial Port:"))
        hbox1.addWidget(self.port_input)
        hbox1.addWidget(btn_connect)
        layout.addLayout(hbox1)

        hbox2 = QHBoxLayout()
        self.cpr_input = QLineEdit(str(self.counts_per_theta_rev))
        hbox2.addWidget(QLabel("Counts per θ-rev:"))
        hbox2.addWidget(self.cpr_input)
        layout.addLayout(hbox2)

        btn_start = QPushButton("Start Rotation (9 RPM)")
        btn_start.clicked.connect(lambda: self.send_theta_velocity_rpm(9))
        btn_stop = QPushButton("Stop Rotation")
        btn_stop.clicked.connect(lambda: self.send_theta_velocity_rpm(0))
        layout.addWidget(btn_start)
        layout.addWidget(btn_stop)

        tab.setLayout(layout)
        self.tabs.addTab(tab, "Rotation")

    def _build_print_tab(self):
        tab = QWidget()
        layout = QVBoxLayout()

        btn_select_video = QPushButton("Select Video File")
        btn_select_video.clicked.connect(self.select_video)
        layout.addWidget(btn_select_video)
        self.video_path = QLineEdit()
        layout.addWidget(self.video_path)

        btn_print = QPushButton("Start Z-Translation Multi-Pass Print")
        btn_print.clicked.connect(self.run_print)
        layout.addWidget(btn_print)

        tab.setLayout(layout)
        self.tabs.addTab(tab, "Print")

    def _build_balance_tab(self):
        tab = QWidget()
        layout = QVBoxLayout()

        btn_balance = QPushButton("Start Real-Time Balancing")
        btn_balance.clicked.connect(self.run_balancing)
        layout.addWidget(btn_balance)

        tab.setLayout(layout)
        self.tabs.addTab(tab, "Balancing")

    def _build_camera_tab(self):
        tab = QWidget()
        layout = QVBoxLayout()

        self.lbl_camera = QLabel()
        self.lbl_camera.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.lbl_camera)
        btn_open_cam = QPushButton("Open Camera")
        btn_open_cam.clicked.connect(self.open_camera)
        layout.addWidget(btn_open_cam)

        tab.setLayout(layout)
        self.tabs.addTab(tab, "Camera")

    # ---------------- Calibration Wizard Handlers ----------------
    def _toggle_sim_mode(self, checked: bool):
        self.bridge.simulation_mode = checked
        self.cal_log.append(f"Simulation mode {'ENABLED' if checked else 'DISABLED'}.")
        if checked and not self.timer.isActive():
            self.timer.start(60)

    def reset_initial_snapshot(self):
        self.initial_frame_locked = False
        self.initial_baseline.clear()
        self.lbl_cal_initial.clear()
        self.lbl_cal_initial.setText("Initial image cleared.\nNext run will capture a new baseline.")
        self.cal_log.append("Cleared initial baseline image and metrics; next step run will capture a fresh baseline.")

    def _on_step_selected(self, row: int):
        if 0 <= row < len(CALIBRATION_STEPS):
            self.current_step_idx = row
            self.reset_initial_snapshot()
            self._refresh_step_ui()

    def _refresh_step_ui(self):
        step = CALIBRATION_STEPS[self.current_step_idx]
        self.step_list.blockSignals(True)
        self.step_list.setCurrentRow(self.current_step_idx)
        for idx, s in enumerate(CALIBRATION_STEPS):
            st = self.step_status[s["id"]]
            self.step_list.item(idx).setText(f"[{st}] {s['title']}")
        self.step_list.blockSignals(False)

        self.lbl_step_title.setText(f"{step['title']}  ({step['mode']})")
        self.lbl_step_goal.setText(f"Procedure: {step['goal']}")
        self.lbl_step_tol.setText(f"Target Tolerance: {step['tolerance']}")
        self.step_progress.setValue(0)

        if step["id"] == "tilt":
            self.lbl_prompt_banner.setText(
                "Manual Step: Click '▶ Run Current Step' to capture the Initial baseline on the left, "
                "physically tilt/rotate the projector, and re-run to compare before vs. after on the right."
            )
            self.lbl_prompt_banner.setStyleSheet(
                "background-color: #fff8e6; border: 1px solid #f0c36d; padding: 8px; border-radius: 4px;"
            )
        else:
            self.lbl_prompt_banner.setText(
                f"Step {self.current_step_idx + 1} of {len(CALIBRATION_STEPS)}: "
                "Click '▶ Run Current Step' to capture Initial (left) and Calibrated (right) images."
            )
            self.lbl_prompt_banner.setStyleSheet(
                "background-color: #eef5ff; border: 1px solid #99c2ff; padding: 8px; border-radius: 4px;"
            )

        if self.bridge.simulation_mode and not self.timer.isActive():
            self.timer.start(60)

    def run_current_calibration_step(self):
        if self.cal_worker and self.cal_worker.isRunning():
            return

        self.cal_data.vial_diameter_mm = self.spin_vial_diam.value()
        self.cal_data.vial_height_mm = self.spin_vial_height.value()

        step = CALIBRATION_STEPS[self.current_step_idx]
        self.btn_run_step.setEnabled(False)
        self.lbl_prompt_banner.setText(f"Running {step['title']}... Compare Initial (left) vs. Current (right).")
        self.cal_log.append(f"--- Starting {step['title']} ---")

        self.cal_worker = CalibrationStepWorker(
            step_id=step["id"],
            bridge=self.bridge,
            cal_data=self.cal_data,
            r_center_mm=self.spin_r_center.value(),
            r_tol_mm=self.spin_r_tol.value(),
            r_step_mm=0.05,
            focus_threshold=self.spin_focus_thresh.value(),
            initial_baseline=self.initial_baseline,
        )
        self.cal_worker.log_signal.connect(self.cal_log.append)
        self.cal_worker.progress_signal.connect(self.step_progress.setValue)
        self.cal_worker.initial_image_signal.connect(self._on_initial_frame)
        self.cal_worker.image_signal.connect(self._on_calibrated_frame)
        self.cal_worker.step_completed.connect(self._on_step_completed)
        self.cal_worker.start()

    def _on_initial_frame(self, bgr_frame: np.ndarray):
        if not self.initial_frame_locked:
            self._display_bgr_on_label(bgr_frame, self.lbl_cal_initial)
            self.initial_frame_locked = True

    def _on_calibrated_frame(self, bgr_frame: np.ndarray):
        self.last_annotated_frame = bgr_frame
        self.show_live_feed = False
        self.btn_toggle_view.setText("Right View: Calibrated Snapshot (Click for Live)")
        self._display_bgr_on_label(bgr_frame, self.lbl_cal_calibrated)

    def _on_step_completed(self, step_id: str, passed: bool, message: str, results: Dict[str, Any]):
        self.btn_run_step.setEnabled(True)
        if results:
            for k, v in results.items():
                if hasattr(self.cal_data, k):
                    setattr(self.cal_data, k, v)

        self.step_status[step_id] = "PASS" if passed else "CHECK"
        self._refresh_step_ui()
        self.step_progress.setValue(100)
        self.cal_log.append(f"[RESULT] {message}")

        if passed:
            self.lbl_prompt_banner.setText(
                f"✓ {message}  Compare Initial (left) vs. Calibrated (right), then click 'Confirm && Move to Next Step ->'."
            )
            self.lbl_prompt_banner.setStyleSheet(
                "background-color: #e8f8ee; border: 1px solid #5cb85c; padding: 8px; border-radius: 4px; font-weight: bold;"
            )
        else:
            self.lbl_prompt_banner.setText(
                f"⚠ {message}  Previous calibration values were preserved."
            )
            self.lbl_prompt_banner.setStyleSheet(
                "background-color: #fdecea; border: 1px solid #d9534f; padding: 8px; border-radius: 4px; font-weight: bold;"
            )

    def advance_to_next_step(self):
        if self.current_step_idx < len(CALIBRATION_STEPS) - 1:
            self.current_step_idx += 1
            self.show_live_feed = True
            self.btn_toggle_view.setText("Right View: Live Feed (Click for Snapshot)")
            self.reset_initial_snapshot()
            self._refresh_step_ui()
        else:
            QMessageBox.information(
                self,
                "Calibration Complete",
                "All 7 calibration stages completed! Click 'Save Calibration JSON' to export parameters."
            )

    def toggle_cal_camera_view(self):
        self.show_live_feed = not self.show_live_feed
        if self.show_live_feed:
            self.btn_toggle_view.setText("Right View: Live Feed (Click for Snapshot)")
        else:
            self.btn_toggle_view.setText("Right View: Calibrated Snapshot (Click for Live)")
            if self.last_annotated_frame is not None:
                self._display_bgr_on_label(self.last_annotated_frame, self.lbl_cal_calibrated)

    def save_calibration_json(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Calibration Config", "config_heliCAL.json", "JSON Files (*.json)"
        )
        if not path:
            return
        with open(path, "w", encoding="utf-8") as f:
            json.dump(asdict(self.cal_data), f, indent=2)
        self.cal_log.append(f"Saved calibration parameters to {path}")
        QMessageBox.information(self, "Calibration Saved", f"Saved to {path}")

    # ---------------- Existing Helpers ----------------
    def connect_esp32(self):
        port = self.port_input.text().strip()
        try:
            self.serial_port = serial.Serial(port, 115200, timeout=0.2)
            QMessageBox.information(self, "ESP32", f"Connected to {port}")
        except Exception as e:
            QMessageBox.critical(self, "ESP32", f"Failed to open {port}: {e}")

    def rpm_to_pulses_per_sec(self, rpm: float) -> int:
        try:
            self.counts_per_theta_rev = int(float(self.cpr_input.text().strip()))
        except Exception:
            self.counts_per_theta_rev = 245426
            self.cpr_input.setText(str(self.counts_per_theta_rev))
        return int(round((rpm * self.counts_per_theta_rev) / 60.0))

    def send_theta_velocity_rpm(self, rpm: float):
        if not self.serial_port:
            QMessageBox.warning(self, "ESP32", "Connect to ESP32 first.")
            return
        pps = self.rpm_to_pulses_per_sec(rpm)
        cmd = bytearray([0x30, 0x01]) + int(pps).to_bytes(4, "little", signed=True)
        try:
            self.serial_port.reset_input_buffer()
            self.serial_port.write(cmd)
            self.serial_port.flush()
            _ = self.serial_port.read(1)
        except Exception as e:
            QMessageBox.critical(self, "UART", f"Failed to send velocity: {e}")

    def select_video(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select MP4 Video", "", "Video Files (*.mp4)")
        if path:
            self.video_path.setText(path)

    def run_print(self):
        video = self.video_path.text().strip()
        if not video:
            QMessageBox.warning(self, "Print", "Select a video file first.")
            return
        cmd = [
            "./cal6_print_z_translation_multi_pass", video, "output.mp4",
            "--crop_height_px", "800", "--cycles_per_pass", "1", "--deg_per_sec", "9"
        ]
        threading.Thread(target=lambda: subprocess.run(cmd, check=True), daemon=True).start()

    def run_balancing(self):
        threading.Thread(target=lambda: subprocess.run(["./cal6_balance"], check=True), daemon=True).start()

    def open_camera(self):
        self.camera = cv2.VideoCapture(0)
        if not self.camera.isOpened():
            QMessageBox.critical(self, "Camera", "Failed to open camera.")
            return
        self.bridge.simulation_mode = False
        self.chk_sim_mode.setChecked(False)
        self.timer.start(30)

    def _display_bgr_on_label(self, bgr_frame: np.ndarray, label: QLabel):
        rgb = cv2.cvtColor(bgr_frame, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb.shape
        img = QImage(rgb.data, w, h, ch * w, QImage.Format_RGB888)
        label.setPixmap(QPixmap.fromImage(img).scaled(
            label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
        ))

    def update_frame(self):
        frame = None
        if self.camera is not None and self.camera.isOpened():
            ret, cam_frame = self.camera.read()
            if ret:
                frame = cam_frame
        elif self.bridge.simulation_mode:
            frame = self.bridge.grab_frame()

        if frame is None:
            return

        if self.lbl_camera.isVisible():
            self._display_bgr_on_label(frame, self.lbl_camera)

        if self.lbl_cal_calibrated.isVisible() and self.show_live_feed:
            overlay = frame.copy()
            h, w = overlay.shape[:2]
            cv2.drawMarker(overlay, (w // 2, h // 2), (0, 255, 255), cv2.MARKER_CROSS, 20, 1)
            cv2.putText(overlay, "LIVE FEED", (15, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 255, 255), 2)
            self._display_bgr_on_label(overlay, self.lbl_cal_calibrated)

    def closeEvent(self, event):
        self.timer.stop()
        if self.cal_worker and self.cal_worker.isRunning():
            self.cal_worker.abort()
            self.cal_worker.wait(1000)
        if self.camera is not None and self.camera.isOpened():
            self.camera.release()
        if self.serial_port is not None and self.serial_port.is_open:
            self.serial_port.close()
        super().closeEvent(event)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    gui = HeliCALGui()
    gui.show()
    sys.exit(app.exec_())