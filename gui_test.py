"""
gui_test.py

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
  python gui_test.py
"""

import sys
import os
import json
import time
import threading

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QTabWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QLineEdit, QTextEdit, QFileDialog, QCheckBox, QMessageBox,
    QSpinBox, QDoubleSpinBox, QGroupBox, QFormLayout, QComboBox
)
import serial

PIPELINE_OK = True
try:
    import gui_test as pipeline
except Exception as e:
    pipeline = None
    PIPELINE_OK = False
    PIPELINE_IMPORT_ERR = str(e)


def _default_cfg():
    if pipeline and hasattr(pipeline, "load_config"):
        return pipeline.load_config()
    return {
        "resolution": 96,
        "num_angles": 120,
        "proj_threshold": 0.5,
        "pixel_size_mm": 0.1,
        "feedrate": 1200,
        "laser_power_on": 255,
        "laser_power_off": 0,
        "dwell_ms": 2,
        "ray_type": "parallel",
    }

def _save_cfg(cfg: dict):
    if pipeline and hasattr(pipeline, "save_config"):
        pipeline.save_config(cfg)


class HeliCALQt(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("HeliCAL Control Center")
        self.resize(980, 720)

        self.serial = None
        self.port = "/dev/ttyTHS1"
        self.baud = 115200

        self.counts_per_theta_rev = 245426
        self._last_enc_pos = None
        self._last_enc_ts = None

        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)

        self._build_tab_pipeline()
        self._build_tab_dc_encoder()
        self._build_tab_steppers()

        self.enc_timer = QTimer(self)
        self.enc_timer.setInterval(500)
        self.enc_timer.timeout.connect(self._poll_encoder)

    def _build_tab_pipeline(self):
        tab = QWidget()
        v = QVBoxLayout(tab)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("STL File:"))
        self.le_stl = QLineEdit("")
        row1.addWidget(self.le_stl, 1)
        btn_browse_stl = QPushButton("Browse")
        btn_browse_stl.clicked.connect(self._browse_stl)
        row1.addWidget(btn_browse_stl)
        v.addLayout(row1)

        self.cb_demo = QCheckBox("Demo Mode (use packaged ring/cube if file missing)")
        self.cb_demo.setChecked(True)
        v.addWidget(self.cb_demo)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Output Dir:"))
        self.le_out = QLineEdit(os.path.join(os.getcwd(), "outputs"))
        row2.addWidget(self.le_out, 1)
        btn_browse_out = QPushButton("Browse")
        btn_browse_out.clicked.connect(self._browse_outdir)
        row2.addWidget(btn_browse_out)
        v.addLayout(row2)

        form = QFormLayout()
        self.sb_res = QSpinBox(); self.sb_res.setRange(16, 512); self.sb_res.setValue(_default_cfg().get("resolution", 96))
        self.sb_ang = QSpinBox(); self.sb_ang.setRange(1, 1080); self.sb_ang.setValue(_default_cfg().get("num_angles", 120))
        self.dsb_thr = QDoubleSpinBox(); self.dsb_thr.setDecimals(3); self.dsb_thr.setRange(0.0, 1.0); self.dsb_thr.setSingleStep(0.01); self.dsb_thr.setValue(_default_cfg().get("proj_threshold", 0.5))
        self.dsb_px = QDoubleSpinBox(); self.dsb_px.setDecimals(4); self.dsb_px.setRange(0.001, 10.0); self.dsb_px.setValue(_default_cfg().get("pixel_size_mm", 0.1))
        self.sb_fr = QSpinBox(); self.sb_fr.setRange(1, 200000); self.sb_fr.setValue(_default_cfg().get("feedrate", 1200))
        self.sb_on = QSpinBox(); self.sb_on.setRange(0, 255); self.sb_on.setValue(_default_cfg().get("laser_power_on", 255))
        self.sb_off = QSpinBox(); self.sb_off.setRange(0, 255); self.sb_off.setValue(_default_cfg().get("laser_power_off", 0))
        self.sb_dw = QSpinBox(); self.sb_dw.setRange(0, 10000); self.sb_dw.setValue(_default_cfg().get("dwell_ms", 2))
        self.cb_ray = QComboBox(); self.cb_ray.addItems(["parallel"]); self.cb_ray.setCurrentText(_default_cfg().get("ray_type", "parallel"))

        form.addRow("Resolution (vox)", self.sb_res)
        form.addRow("# Angles", self.sb_ang)
        form.addRow("Threshold (0..1)", self.dsb_thr)
        form.addRow("Pixel size (mm)", self.dsb_px)
        form.addRow("Feedrate (mm/min)", self.sb_fr)
        form.addRow("Laser ON PWM (0..255)", self.sb_on)
        form.addRow("Laser OFF PWM (0..255)", self.sb_off)
        form.addRow("Dwell per px (ms)", self.sb_dw)
        form.addRow("Ray Type", self.cb_ray)
        grp = QGroupBox("Pipeline Parameters")
        grp.setLayout(form)
        v.addWidget(grp)

        row3 = QHBoxLayout()
        self.btn_run = QPushButton("Run Pipeline")
        self.btn_run.clicked.connect(self._run_pipeline_clicked)
        row3.addWidget(self.btn_run)

        self.btn_save_cfg = QPushButton("Save Config")
        self.btn_save_cfg.clicked.connect(self._save_cfg_clicked)
        row3.addWidget(self.btn_save_cfg)
        v.addLayout(row3)

        self.txt_log = QTextEdit(); self.txt_log.setReadOnly(True)
        v.addWidget(QLabel("Status Log (pipeline):"))
        v.addWidget(self.txt_log, 1)

        if not PIPELINE_OK:
            self._append_log(f"[WARN] Could not import pipeline helpers from gui_test.py: {PIPELINE_IMPORT_ERR}")
            self.btn_run.setEnabled(False)

        self.tabs.addTab(tab, "Pipeline")

    def _append_log(self, msg: str):
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        self.txt_log.append(f"[{ts}] {msg}")

    def _browse_stl(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choose STL", "", "STL files (*.stl);;All files (*.*)")
        if path:
            self.le_stl.setText(path)

    def _browse_outdir(self):
        d = QFileDialog.getExistingDirectory(self, "Choose Output Directory", self.le_out.text())
        if d:
            self.le_out.setText(d)

    def _save_cfg_clicked(self):
        cfg = self._cfg_from_ui()
        _save_cfg(cfg)
        QMessageBox.information(self, "Saved", "Configuration saved.")

    def _cfg_from_ui(self):
        return {
            "resolution": int(self.sb_res.value()),
            "num_angles": int(self.sb_ang.value()),
            "proj_threshold": float(self.dsb_thr.value()),
            "pixel_size_mm": float(self.dsb_px.value()),
            "feedrate": int(self.sb_fr.value()),
            "laser_power_on": int(self.sb_on.value()),
            "laser_power_off": int(self.sb_off.value()),
            "dwell_ms": int(self.sb_dw.value()),
            "ray_type": self.cb_ray.currentText(),
        }

    def _run_pipeline_clicked(self):
        if not PIPELINE_OK:
            QMessageBox.critical(self, "Pipeline", "Pipeline helpers not available. Ensure gui_test.py is importable.")
            return
        stl = self.le_stl.text().strip()
        out_dir = self.le_out.text().strip()
        os.makedirs(out_dir, exist_ok=True)
        cfg = self._cfg_from_ui()
        _save_cfg(cfg)

        def worker():
            try:
                resolved = pipeline.resolve_stl_path(stl if stl else None, self.cb_demo.isChecked())
                self._append_log(f"=== Run start: STL='{resolved}' (demo={self.cb_demo.isChecked()}) ===")
                tg = pipeline.voxelize_stl(resolved, cfg["resolution"])
                recon_array, sino, recon = pipeline.run_projection(tg, cfg["num_angles"], ray_type=cfg.get("ray_type", "parallel"))
                spath, rpath = pipeline.save_projection_images(out_dir, sino, recon_array)
                pipeline.save_angle_montage(out_dir, sino, n_cols=10)
                gpath = pipeline.write_gcode_from_recon_slice(out_dir, recon_array, cfg)
                self._append_log(f"Saved {spath}")
                self._append_log(f"Saved {rpath}")
                self._append_log(f"Saved {os.path.join(out_dir, 'angle_montage.png')}")
                self._append_log(f"Saved {gpath}")
                self._append_log(f"=== Run done ===")
                QMessageBox.information(self, "Done", f"Outputs saved to:\\n{out_dir}")
            except Exception as e:
                self._append_log(f"[ERROR] Pipeline failed: {e}")
                QMessageBox.critical(self, "Pipeline Error", str(e))

        threading.Thread(target=worker, daemon=True).start()

    def _build_tab_dc_encoder(self):
        tab = QWidget()
        v = QVBoxLayout(tab)

        ser_row = QHBoxLayout()
        self.le_port = QLineEdit(self.port)
        self.le_baud = QLineEdit(str(self.baud))
        btn_conn = QPushButton("Connect")
        btn_conn.clicked.connect(self._connect_serial)
        btn_disc = QPushButton("Disconnect")
        btn_disc.clicked.connect(self._disconnect_serial)
        ser_row.addWidget(QLabel("Port:")); ser_row.addWidget(self.le_port)
        ser_row.addWidget(QLabel("Baud:")); ser_row.addWidget(self.le_baud)
        ser_row.addWidget(btn_conn); ser_row.addWidget(btn_disc)
        v.addLayout(ser_row)

        c_row = QHBoxLayout()
        self.le_cpr = QLineEdit(str(self.counts_per_theta_rev))
        c_row.addWidget(QLabel("Counts per θ-rev:"))
        c_row.addWidget(self.le_cpr)
        v.addLayout(c_row)

        rpm_row = QHBoxLayout()
        self.dsb_rpm = QDoubleSpinBox(); self.dsb_rpm.setRange(-2000.0, 2000.0); self.dsb_rpm.setDecimals(2); self.dsb_rpm.setValue(9.0)
        btn_set = QPushButton("Set Velocity")
        btn_set.clicked.connect(self._send_theta_velocity_rpm)
        btn_stop = QPushButton("Stop (0 rpm)")
        btn_stop.clicked.connect(lambda: self._send_theta_velocity_rpm(stop=True))
        rpm_row.addWidget(QLabel("RPM:")); rpm_row.addWidget(self.dsb_rpm); rpm_row.addWidget(btn_set); rpm_row.addWidget(btn_stop)
        v.addLayout(rpm_row)

        mon_group = QGroupBox("Encoder Monitor (2 Hz)")
        form = QFormLayout()
        self.lbl_pos = QLabel("—")
        self.lbl_velpps = QLabel("—")
        self.lbl_velrpm = QLabel("—")
        form.addRow("Position (counts)", self.lbl_pos)
        form.addRow("Velocity (pulses/s)", self.lbl_velpps)
        form.addRow("Velocity (rpm)", self.lbl_velrpm)
        mon_group.setLayout(form)
        v.addWidget(mon_group)

        poll_row = QHBoxLayout()
        btn_poll_on = QPushButton("Start Poll")
        btn_poll_on.clicked.connect(lambda: self.enc_timer.start())
        btn_poll_off = QPushButton("Stop Poll")
        btn_poll_off.clicked.connect(lambda: self.enc_timer.stop())
        poll_row.addWidget(btn_poll_on); poll_row.addWidget(btn_poll_off)
        v.addLayout(poll_row)

        self.tabs.addTab(tab, "DC Motor & Encoder")

    def _connect_serial(self):
        try:
            port = self.le_port.text().strip()
            baud = int(self.le_baud.text().strip())
            self.serial = serial.Serial(port, baudrate=baud, timeout=0.2)
            QMessageBox.information(self, "Serial", f"Connected to {port}")
        except Exception as e:
            QMessageBox.critical(self, "Serial", f"Failed to open port: {e}")

    def _disconnect_serial(self):
        try:
            if self.serial and self.serial.is_open:
                self.serial.close()
        except Exception:
            pass
        self.serial = None
        QMessageBox.information(self, "Serial", "Disconnected.")

    def _rpm_to_pps(self, rpm: float) -> int:
        try:
            self.counts_per_theta_rev = int(float(self.le_cpr.text().strip()))
        except Exception:
            self.counts_per_theta_rev = 245426
            self.le_cpr.setText(str(self.counts_per_theta_rev))
        return int(round((rpm * self.counts_per_theta_rev) / 60.0))

    def _send_theta_velocity_rpm(self, stop=False):
        if not self.serial or not self.serial.is_open:
            QMessageBox.warning(self, "UART", "Connect to ESP32 first.")
            return
        rpm = 0.0 if stop else float(self.dsb_rpm.value())
        pps = self._rpm_to_pps(rpm)
        packet = bytearray([0x30, 0x01]) + int(pps).to_bytes(4, "little", signed=True)
        try:
            self.serial.reset_input_buffer()
            self.serial.write(packet)
            self.serial.flush()
            _ = self.serial.read(1)
        except Exception as e:
            QMessageBox.critical(self, "UART", f"Send failed: {e}")

    def _poll_encoder(self):
        if not self.serial or not self.serial.is_open:
            return
        try:
            pkt = bytearray([0x10, 0xFF, 0, 0, 0, 0])
            self.serial.write(pkt)
            self.serial.flush()
            raw = self.serial.read(20)
            if len(raw) != 20:
                return
            vals = [int.from_bytes(raw[i:i+4], "little", signed=True) for i in range(0, 20, 4)]
            theta_pos = vals[2]
            now = time.time()
            self.lbl_pos.setText(str(theta_pos))
            if self._last_enc_pos is not None and self._last_enc_ts is not None:
                dt = max(1e-6, now - self._last_enc_ts)
                dcounts = theta_pos - self._last_enc_pos
                pps = dcounts / dt
                rpm = (pps * 60.0) / max(1, self.counts_per_theta_rev)
                self.lbl_velpps.setText(f"{pps:.1f}")
                self.lbl_velrpm.setText(f"{rpm:.3f}")
            self._last_enc_pos = theta_pos
            self._last_enc_ts = now
        except Exception:
            pass

    def _build_tab_steppers(self):
        tab = QWidget()
        v = QVBoxLayout(tab)

        info = QLabel(
            "Basic stepper controls (placeholders). Align command bytes with firmware.\\n"
            "Suggested protocol (example):\\n"
            "  0x50 axis enable  : [0x50, axis_id, 1|0, 0, 0, 0]\\n"
            "  0x51 jog steps    : [0x51, axis_id, <int32 steps>]\\n"
            "  0x52 set position : [0x52, axis_id, <int32 steps>]\\n"
            "  0x53 set speed    : [0x53, axis_id, <int32 steps_per_s>]\\n"
        )
        info.setWordWrap(True)
        v.addWidget(info)

        axis_row = QHBoxLayout()
        self.cb_axis = QComboBox()
        self.cb_axis.addItems(["X1", "Y1", "Z1", "X2", "Y2", "Z2"])
        axis_row.addWidget(QLabel("Axis:"))
        axis_row.addWidget(self.cb_axis)
        v.addLayout(axis_row)

        en_row = QHBoxLayout()
        btn_en = QPushButton("Enable")
        btn_en.clicked.connect(lambda: self._send_stepper_enable(True))
        btn_dis = QPushButton("Disable")
        btn_dis.clicked.connect(lambda: self._send_stepper_enable(False))
        en_row.addWidget(btn_en); en_row.addWidget(btn_dis)
        v.addLayout(en_row)

        jog_row = QHBoxLayout()
        self.sb_jog = QSpinBox(); self.sb_jog.setRange(-2000000, 2000000); self.sb_jog.setValue(200)
        btn_jog = QPushButton("Jog (steps)")
        btn_jog.clicked.connect(self._send_stepper_jog)
        jog_row.addWidget(QLabel("Steps:")); jog_row.addWidget(self.sb_jog); jog_row.addWidget(btn_jog)
        v.addLayout(jog_row)

        pos_row = QHBoxLayout()
        self.sb_pos = QSpinBox(); self.sb_pos.setRange(-200000000, 200000000); self.sb_pos.setValue(0)
        btn_pos = QPushButton("Set Target Position (steps)")
        btn_pos.clicked.connect(self._send_stepper_setpos)
        pos_row.addWidget(QLabel("Target:")); pos_row.addWidget(self.sb_pos); pos_row.addWidget(btn_pos)
        v.addLayout(pos_row)

        spd_row = QHBoxLayout()
        self.sb_spd = QSpinBox(); self.sb_spd.setRange(0, 2000000); self.sb_spd.setValue(2000)
        btn_spd = QPushButton("Set Speed (steps/s)")
        btn_spd.clicked.connect(self._send_stepper_speed)
        spd_row.addWidget(QLabel("Speed:")); spd_row.addWidget(self.sb_spd); spd_row.addWidget(btn_spd)
        v.addLayout(spd_row)

        self.tabs.addTab(tab, "Steppers")

    def _axis_id(self):
        mapping = {"X1":0, "Y1":1, "Z1":2, "X2":3, "Y2":4, "Z2":5}
        return mapping[self.cb_axis.currentText()]

    def _uart_write(self, data: bytes):
        if not self.serial or not self.serial.is_open:
            QMessageBox.warning(self, "UART", "Connect to ESP32 first (on DC/Encoder tab).")
            return False
        try:
            self.serial.write(data)
            self.serial.flush()
            return True
        except Exception as e:
            QMessageBox.critical(self, "UART", f"UART write failed: {e}")
            return False

    def _send_stepper_enable(self, enable: bool):
        axis = self._axis_id()
        pkt = bytearray([0x50, axis, 1 if enable else 0, 0, 0, 0])
        self._uart_write(pkt)

    def _send_stepper_jog(self):
        axis = self._axis_id()
        steps = int(self.sb_jog.value())
        pkt = bytearray([0x51, axis]) + int(steps).to_bytes(4, "little", signed=True)
        self._uart_write(pkt)

    def _send_stepper_setpos(self):
        axis = self._axis_id()
        pos = int(self.sb_pos.value())
        pkt = bytearray([0x52, axis]) + int(pos).to_bytes(4, "little", signed=True)
        self._uart_write(pkt)

    def _send_stepper_speed(self):
        axis = self._axis_id()
        spd = int(self.sb_spd.value())
        pkt = bytearray([0x53, axis]) + int(spd).to_bytes(4, "little", signed=True)
        self._uart_write(pkt)


def main():
    app = QApplication(sys.argv)
    w = HeliCALQt()
    w.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
