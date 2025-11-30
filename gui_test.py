"""
gui_test.py

Purpose:
  * Work backwards from OUTPUTS (images + G-code) without lab hardware.
  * Flexible: accepts ANY .stl when available, OR falls back to built-in demo assets via vamtoolbox.resources.
  * Outputs:
      - Projection images (PNGs)
      - Toy G-code from a thresholded reconstruction slice
      - Status log + editable JSON config
  * "Demo Mode" toggle guarantees a successful off-lab run.

Changes vs previous:
  - Added DEMO MODE (uses packaged demo STL, e.g., 'ring.stl', if user path is missing)
  - Graceful file checks with helpful error messages
  - Auto-tries vam.resources.load(<basename>) when a path is missing
  - Saves an angle-sweep montage PNG

Dependencies:
  - numpy, matplotlib
  - vamtoolbox (ASTRA if available)

Run:
  python gui_test.py
"""


import sys
import os
import time
import socket
from queue import Queue, Empty
from pathlib import Path

from PyQt5.QtCore import Qt, QTimer, QObject, pyqtSignal, QThread, QEvent, pyqtSlot
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QTabWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QLineEdit, QTextEdit, QFileDialog, QCheckBox, QMessageBox,
    QSpinBox, QDoubleSpinBox, QGroupBox, QFormLayout, QComboBox, QDialog, QGridLayout
)
import serial
import vamtoolbox as vam
from vamtoolbox.geometry import TargetGeometry, ProjectionGeometry, Sinogram, Reconstruction
import vamtoolbox.projector as projector_module
import numpy as np
import matplotlib.pyplot as plt

# Compatibility for older code that uses np.bool
np.bool = bool

PIPELINE_OK = True
try:
    import pipeline_helpers as pipeline
except Exception as e:
    pipeline = None
    PIPELINE_OK = False
    PIPELINE_IMPORT_ERR = str(e)
    import gui_test as pipeline
except Exception as e:
    pipeline = None
    PIPELINE_OK = False
    PIPELINE_IMPORT_ERR = str(e)

try:
    import paramiko
except ImportError:
    paramiko = None


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


class PasswordDialog(QDialog):
    def __init__(self, parent, user, host):
        super().__init__(parent)
        self.setWindowTitle("Remote Login Required")
        self._password = ""
        self.setModal(True)
        self.setMinimumWidth(360)

        label = QLabel(f"Enter password for system: {user}@{host}")
        self.le_password = QLineEdit()
        self.le_password.setEchoMode(QLineEdit.Password)
        self.le_password.installEventFilter(self)

        self.btn_enter = QPushButton("Enter")
        self.btn_enter.setAutoDefault(False)
        self.btn_enter.setDefault(False)
        self.btn_enter.clicked.connect(self._on_submit)

        layout = QVBoxLayout(self)
        layout.addWidget(label)
        layout.addWidget(self.le_password)
        layout.addWidget(self.btn_enter)

    def eventFilter(self, obj, event):
        if obj is self.le_password and event.type() == QEvent.KeyPress:
            if event.key() in (Qt.Key_Return, Qt.Key_Enter):
                return True
        return super().eventFilter(obj, event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            event.ignore()
            return
        super().keyPressEvent(event)

    def _on_submit(self):
        self._password = self.le_password.text()
        self.accept()

    def password(self):
        return self._password


class SSHCommandWorker(QObject):
    log = pyqtSignal(str)
    success = pyqtSignal()
    failed = pyqtSignal(str)
    auth_failed = pyqtSignal()
    connection_lost = pyqtSignal(str)

    def __init__(self, host, user, password, remote_dir):
        super().__init__()
        self.host = host
        self.user = user
        self.password = password
        self.remote_dir = remote_dir
        self.port = 22
        self.compile_cmd = (
            "g++ -std=c++17 -Wall -Wextra -pthread master_queue.cpp "
            "Esp32UART.cpp TicController.cpp HeliCalHelper.cpp LED.cpp "
            "DLPC900.cpp window_manager.cpp -I/usr/include/hidapi "
            "-lhidapi-hidraw -o master_queue"
        )
        self._client = None
        self._stdin = None
        self._stdout = None
        self._stderr = None
        self._channel = None
        self._commands = Queue()
        self._running = False
        self._connected = False

    @pyqtSlot(str)
    def enqueue_command(self, command: str):
        cmd = (command or "").strip()
        if cmd:
            self._commands.put(cmd)

    @pyqtSlot()
    def stop(self):
        self._commands.put("__disconnect__")

    def _emit_log(self, message):
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        self.log.emit(f"[SSH] [{ts}] {message}")

    def run(self):
        if paramiko is None:
            self.failed.emit("Paramiko is not installed. Install it to enable remote automation.")
            return

        try:
            self._client = paramiko.SSHClient()
            self._client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            self._emit_log(f"Connecting to {self.user}@{self.host} ...")
            self._client.connect(
                hostname=self.host,
                port=self.port,
                username=self.user,
                password=self.password,
                timeout=10,
                allow_agent=False,
                look_for_keys=False,
            )
            self._emit_log("SSH connection established.")
            self._run_remote_command(f"cd {self.remote_dir} && {self.compile_cmd}")
            self._start_master_queue()
            self._running = True
            self._connected = True
            self.success.emit()
            while self._running:
                self._pump_stdout()
                try:
                    cmd = self._commands.get(timeout=0.2)
                except Empty:
                    continue
                if cmd == "__disconnect__":
                    break
                self._send_line(cmd)
            self._emit_log("Stopping remote session.")
        except paramiko.AuthenticationException:
            self.auth_failed.emit()
        except Exception as exc:
            if self._connected:
                self.connection_lost.emit(str(exc))
            else:
                self.failed.emit(str(exc))
        finally:
            self._running = False
            self._cleanup()

    def _run_remote_command(self, command, needs_sudo=False):
        self._emit_log(f"Running: {command}")
        stdin, stdout, stderr = self._client.exec_command(command, get_pty=needs_sudo)
        try:
            if needs_sudo:
                stdin.write(self.password + "\n")
                stdin.flush()
            out = stdout.read().decode(errors="ignore").strip()
            err = stderr.read().decode(errors="ignore").strip()
            exit_status = stdout.channel.recv_exit_status()
            if out:
                self._emit_log(out)
            if err:
                self._emit_log(f"[stderr] {err}")
            if exit_status != 0:
                raise RuntimeError(f"Remote command failed ({exit_status})")
        finally:
            stdin.close()
            stdout.close()
            stderr.close()

    def _start_master_queue(self):
        self._emit_log("Launching master_queue (interactive).")
        self._stdin, self._stdout, self._stderr = self._client.exec_command(
            f"cd {self.remote_dir} && sudo -S ./master_queue",
            get_pty=True,
        )
        self._channel = self._stdout.channel
        self._stdin.write(self.password + "\n")
        self._stdin.flush()

    def _pump_stdout(self):
        if not self._channel:
            return
        try:
            while self._channel.recv_ready():
                data = self._channel.recv(4096).decode(errors="ignore")
                if data:
                    for line in data.replace("\r", "").splitlines():
                        if line.strip():
                            self._emit_log(line.strip())
            if self._channel.exit_status_ready():
                raise RuntimeError("Remote process exited.")
        except Exception:
            raise

    def _send_line(self, command):
        if not self._stdin:
            raise RuntimeError("Remote session not ready.")
        self._emit_log(f"> {command}")
        self._stdin.write(command.strip() + "\n")
        self._stdin.flush()

    def _cleanup(self):
        try:
            if self._stdin:
                try:
                    self._stdin.close()
                except Exception:
                    pass
            if self._stdout:
                try:
                    self._stdout.close()
                except Exception:
                    pass
            if self._stderr:
                try:
                    self._stderr.close()
                except Exception:
                    pass
            if self._channel:
                try:
                    self._channel.close()
                except Exception:
                    pass
            if self._client:
                self._client.close()
        finally:
            self._client = None
            self._stdin = None
            self._stdout = None
            self._stderr = None
            self._channel = None


class PipelineWorker(QObject):
    log = pyqtSignal(str)
    done = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, stl, out_dir, cfg, demo_mode):
        super().__init__()
        self.stl = stl
        self.out_dir = out_dir
        self.cfg = cfg
        self.demo_mode = demo_mode

    def _emit_log(self, msg):
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        self.log.emit(f"[{ts}] {msg}")

    def run(self):
        if not PIPELINE_OK:
            self.failed.emit("Pipeline helpers not available (gui_test.py import failed).")
            return
        try:
            resolved = pipeline.resolve_stl_path(self.stl if self.stl else None, self.demo_mode)
            self._emit_log(f"=== Run start: STL='{resolved}' (demo={self.demo_mode}) ===")
            tg = pipeline.voxelize_stl(resolved, self.cfg["resolution"])
            recon_array, sino, recon = pipeline.run_projection(tg, self.cfg["num_angles"], ray_type=self.cfg.get("ray_type", "parallel"))
            spath, rpath = pipeline.save_projection_images(self.out_dir, sino, recon_array)
            pipeline.save_angle_montage(self.out_dir, sino, n_cols=10)
            gpath = pipeline.write_gcode_from_recon_slice(self.out_dir, recon_array, self.cfg)
            
            # Generate video preview
            vpath = pipeline.save_reconstruction_video(self.out_dir, sino)
            
            self._emit_log(f"Saved {spath}")
            self._emit_log(f"Saved {rpath}")
            self._emit_log(f"Saved {os.path.join(self.out_dir, 'angle_montage.png')}")
            self._emit_log(f"Saved {gpath}")
            if vpath:
                self._emit_log(f"Saved {vpath}")
            self._emit_log("=== Run done ===")
            self.done.emit(self.out_dir)
        except Exception as e:
            self.failed.emit(str(e))


class HeliCALQt(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("HeliCAL Control Panel")
        self.resize(980, 720)

        self.serial = None
        self.port = "/dev/ttyTHS1"
        self.baud = 115200

        self.ssh_host = "192.168.0.123"
        self.ssh_user = "jacob"
        self.remote_dir = "Desktop/HeliCAL_Final"
        self.wifi_name = "AirBears9000"
        self.wifi_password = "somecalpun"
        self._auto_bootstrap_started = False
        self._ssh_connected = False
        self._password_dialog_open = False
        self._ssh_connecting = False
        self.txt_gcode_log = None
        self.le_jog_step = None
        self.le_jog_feed = None

        self.counts_per_theta_rev = 245426
        self._last_enc_pos = None
        self._last_enc_ts = None

        self.tabs = QTabWidget()
        self.connection_indicator = QLabel()
        self.connection_indicator.setFixedSize(18, 18)
        self.connection_indicator.setToolTip("SSH Connection Status")
        self.btn_manual_connect = QPushButton("Connect")
        self.btn_manual_connect.setFixedWidth(80)
        self.btn_manual_connect.clicked.connect(lambda: self._initiate_connection(manual=True))
        self.btn_manual_disconnect = QPushButton("Disconnect")
        self.btn_manual_disconnect.setFixedWidth(100)
        self.btn_manual_disconnect.clicked.connect(self._disconnect_clicked)
        self.btn_manual_disconnect.setEnabled(False)
        self._update_connection_indicator()

        top_bar = QHBoxLayout()
        top_bar.addStretch(1)
        top_bar.addWidget(self.connection_indicator)
        top_bar.addWidget(self.btn_manual_connect)
        top_bar.addWidget(self.btn_manual_disconnect)

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.addLayout(top_bar)
        layout.addWidget(self.tabs)
        self.setCentralWidget(central)

        self._build_tab_pipeline()
        self._build_tab_dc_encoder()
        self._build_tab_steppers()

        self.enc_timer = QTimer(self)
        self.enc_timer.setInterval(500)
        self.enc_timer.timeout.connect(self._poll_encoder)

        self._thread = None
        self._worker = None
        self._ssh_thread = None
        self._ssh_worker = None

        QTimer.singleShot(750, self._initiate_connection)

    def _update_connection_indicator(self):
        color = "#1f8bff" if self._ssh_connected else "#c22525"
        self.connection_indicator.setStyleSheet(
            f"background-color: {color}; border-radius: 9px; border: 1px solid #333;"
        )
        self.btn_manual_connect.setEnabled(not self._ssh_connected and not self._ssh_connecting)
        if self.btn_manual_disconnect:
            self.btn_manual_disconnect.setEnabled(self._ssh_connected)

    def _initiate_connection(self, manual=False):
        if self._ssh_connected:
            if manual:
                QMessageBox.information(self, "SSH", "Already connected to the Jetson.")
            return
        if not self._auto_bootstrap_started:
            self._auto_bootstrap_started = True
        elif not manual:
            return
        if self._ssh_connecting:
            return
        if self._ssh_thread and self._ssh_thread.isRunning():
            return
        if paramiko is None:
            self._append_log("[SSH] Paramiko is not installed; skipping automatic connection.")
            QMessageBox.warning(self, "SSH Unavailable", "Paramiko is required for remote connection.")
            return
        if not self._probe_ssh_host():
            self._show_connection_failed_message()
            return
        self._prompt_remote_password()

    def _probe_ssh_host(self):
        try:
            with socket.create_connection((self.ssh_host, 22), timeout=3):
                return True
        except OSError as exc:
            self._append_log(f"[SSH] Probe error: {exc}")
            return False

    def _show_connection_failed_message(self):
        QMessageBox.critical(
            self,
            "Connection failed!",
            "Connection failed!\nPlease make sure you are connected to the WiFI network:\n"
            f"{self.wifi_name}\nPassword: {self.wifi_password}",
        )

    def _prompt_remote_password(self):
        if self._password_dialog_open or self._ssh_connecting or self._ssh_connected:
            return
        self._password_dialog_open = True
        dlg = PasswordDialog(self, self.ssh_user, self.ssh_host)
        result = dlg.exec_()
        self._password_dialog_open = False
        if result == QDialog.Accepted:
            password = dlg.password()
            if password:
                self._ssh_connecting = True
                self._update_connection_indicator()
                self._launch_ssh_worker(password)
            else:
                QMessageBox.warning(self, "Password Required", "Please enter a password to continue.")
                QTimer.singleShot(0, self._prompt_remote_password)

    def _disconnect_clicked(self):
        if not self._ssh_connected or not self._ssh_worker:
            QMessageBox.information(self, "SSH", "System is not connected.")
            return
        confirm = QMessageBox.question(
            self,
            "Shutdown Jetson",
            "Send 'sudo shutdown now' to the Jetson? This will disconnect the system.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        try:
            self._ssh_worker.enqueue_command("sudo shutdown now")
            self._ssh_worker.stop()
        except Exception as exc:
            QMessageBox.warning(self, "SSH", f"Failed to send shutdown: {exc}")

    def _launch_ssh_worker(self, password):
        if self._ssh_thread and self._ssh_thread.isRunning():
            self._shutdown_ssh_worker()
        self._ssh_thread = QThread()
        self._ssh_worker = SSHCommandWorker(self.ssh_host, self.ssh_user, password, self.remote_dir)
        self._ssh_worker.moveToThread(self._ssh_thread)
        self._ssh_thread.started.connect(self._ssh_worker.run)
        self._ssh_worker.log.connect(self._append_connection_log)
        self._ssh_worker.success.connect(self._on_ssh_success)
        self._ssh_worker.failed.connect(self._on_ssh_failed)
        self._ssh_worker.auth_failed.connect(self._on_ssh_auth_failed)
        self._ssh_worker.connection_lost.connect(self._on_ssh_connection_lost)
        self._ssh_thread.finished.connect(self._on_ssh_thread_finished)
        self._ssh_thread.finished.connect(self._ssh_thread.deleteLater)
        self._ssh_thread.start()

    def _shutdown_ssh_worker(self):
        self._ssh_connecting = False
        self._update_connection_indicator()
        if self._ssh_worker:
            try:
                self._ssh_worker.stop()
            except Exception:
                pass
        if self._ssh_thread:
            self._ssh_thread.quit()
            self._ssh_thread.wait(2000)
            self._ssh_thread = None
            self._ssh_worker = None

    def _on_ssh_thread_finished(self):
        self._ssh_thread = None
        self._ssh_worker = None

    def _on_ssh_success(self):
        self._ssh_connecting = False
        self._ssh_connected = True
        self._update_connection_indicator()
        QMessageBox.information(self, "Connection Successful!", "Connection Successful!")

    def _on_ssh_failed(self, err):
        self._ssh_connecting = False
        self._ssh_connected = False
        self._update_connection_indicator()
        self._append_log(f"[SSH] Failure: {err}")
        self._show_connection_failed_message()

    def _on_ssh_auth_failed(self):
        self._ssh_connecting = False
        self._ssh_connected = False
        self._update_connection_indicator()
        QMessageBox.warning(self, "Incorrect password!", "Incorrect password!\nPlease try again!")

    def _on_ssh_connection_lost(self, reason: str):
        self._ssh_connecting = False
        self._ssh_connected = False
        self._update_connection_indicator()
        self._append_log(f"[SSH] Connection lost: {reason}")
        QMessageBox.critical(self, "SSH Disconnected", f"Connection lost:\n{reason}\nUse Connect to retry.")
        # Allow a fresh manual reconnect without auto-prompt loops
        self._auto_bootstrap_started = False

    def _append_connection_log(self, msg: str):
        self._append_log(msg)
        self._append_gcode_log(msg)
        QTimer.singleShot(0, self._prompt_remote_password)

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
        self.txt_log.append(msg)

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

        if getattr(self, "_thread", None):
            try:
                self._thread.quit()
                self._thread.wait(100)
            except Exception:
                pass

        self._thread = QThread()
        self._worker = PipelineWorker(stl, out_dir, cfg, self.cb_demo.isChecked())
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.log.connect(self._append_log)
        self._worker.done.connect(self._on_pipeline_done)
        self._worker.failed.connect(self._on_pipeline_failed)
        self._worker.done.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.start()

    def _on_pipeline_done(self, out_dir: str):
        QMessageBox.information(self, "Done", f"Outputs saved to:\n{out_dir}")

    def _on_pipeline_failed(self, err: str):
        QMessageBox.critical(self, "Pipeline Error", err)

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
        layout = QVBoxLayout(tab)

        motion_group = QGroupBox("Motion Commands")
        motion_form = QFormLayout()

        def _axis_inputs(placeholders):
            row = QHBoxLayout()
            edits = []
            for text in placeholders:
                le = QLineEdit()
                le.setPlaceholderText(text)
                row.addWidget(le)
                edits.append(le)
            return row, edits

        g0_row, g0_edits = _axis_inputs(["R (mm)", "T (mm)", "Z (mm)"])
        self.le_g0_r, self.le_g0_t, self.le_g0_z = g0_edits
        btn_g0 = QPushButton("Send G0 (Rapid)")
        btn_g0.clicked.connect(lambda: self._send_axis_command("G0", {
            "R": self.le_g0_r,
            "T": self.le_g0_t,
            "Z": self.le_g0_z,
        }))
        g0_row.addWidget(btn_g0)
        motion_form.addRow("G0 Rapid", g0_row)

        g1_row, g1_edits = _axis_inputs(["R (mm)", "T (mm)", "Z (mm)"])
        self.le_g1_r, self.le_g1_t, self.le_g1_z = g1_edits
        self.le_g1_fr = QLineEdit(); self.le_g1_fr.setPlaceholderText("FR (mm/min)")
        self.le_g1_ft = QLineEdit(); self.le_g1_ft.setPlaceholderText("FT (mm/min)")
        self.le_g1_fz = QLineEdit(); self.le_g1_fz.setPlaceholderText("FZ (mm/min)")
        g1_row.addWidget(self.le_g1_fr)
        g1_row.addWidget(self.le_g1_ft)
        g1_row.addWidget(self.le_g1_fz)
        btn_g1 = QPushButton("Send G1 (Linear)")
        btn_g1.clicked.connect(lambda: self._send_axis_command(
            "G1",
            {"R": self.le_g1_r, "T": self.le_g1_t, "Z": self.le_g1_z},
            self._collect_feedrates()
        ))
        g1_row.addWidget(btn_g1)
        motion_form.addRow("G1 Linear", g1_row)
        motion_group.setLayout(motion_form)
        layout.addWidget(motion_group)

        wait_group = QGroupBox("Timing / Flow Control")
        wait_layout = QHBoxLayout()
        self.sb_g4_wait = QDoubleSpinBox(); self.sb_g4_wait.setDecimals(1); self.sb_g4_wait.setRange(0.1, 3600.0); self.sb_g4_wait.setValue(10.0)
        self.sb_g4_wait.setSuffix(" s")
        btn_g4 = QPushButton("Send G4 (Pause)")
        btn_g4.clicked.connect(self._send_g4_wait)
        btn_g5 = QPushButton("G5 (Wait for RPM)")
        btn_g5.clicked.connect(lambda: self._send_gcode_command("G5"))
        btn_g6 = QPushButton("G6 (Wait for Metrology)")
        btn_g6.clicked.connect(lambda: self._send_gcode_command("G6"))
        wait_layout.addWidget(QLabel("G4 Duration:"))
        wait_layout.addWidget(self.sb_g4_wait)
        wait_layout.addWidget(btn_g4)
        wait_layout.addWidget(btn_g5)
        wait_layout.addWidget(btn_g6)
        wait_group.setLayout(wait_layout)
        layout.addWidget(wait_group)

        control_group = QGroupBox("Machine / Axis Control")
        control_layout = QGridLayout()
        self.sb_g33_rpm = QSpinBox(); self.sb_g33_rpm.setRange(0, 5000); self.sb_g33_rpm.setValue(1000)
        btn_g33 = QPushButton("G33 (A RPM)")
        btn_g33.clicked.connect(lambda: self._send_gcode_command(f"G33 A{self.sb_g33_rpm.value()}"))
        control_layout.addWidget(QLabel("A-axis RPM:"), 0, 0)
        control_layout.addWidget(self.sb_g33_rpm, 0, 1)
        control_layout.addWidget(btn_g33, 0, 2)

        self.sb_feed_rate = QSpinBox(); self.sb_feed_rate.setRange(1, 1000000); self.sb_feed_rate.setValue(100)
        btn_feed = QPushButton("Set Feed (F)")
        btn_feed.clicked.connect(lambda: self._send_gcode_command(f"F{self.sb_feed_rate.value()}"))
        control_layout.addWidget(QLabel("Feed Rate (mm/s):"), 1, 0)
        control_layout.addWidget(self.sb_feed_rate, 1, 1)
        control_layout.addWidget(btn_feed, 1, 2)

        btn_m17 = QPushButton("M17 (Motors ON)")
        btn_m17.clicked.connect(lambda: self._send_gcode_command("M17"))
        btn_m18 = QPushButton("M18 (Motors OFF)")
        btn_m18.clicked.connect(lambda: self._send_gcode_command("M18"))
        btn_m112 = QPushButton("M112 (E-Stop)")
        btn_m112.clicked.connect(lambda: self._send_gcode_command("M112"))
        btn_g28 = QPushButton("G28 (Home)")
        btn_g28.clicked.connect(lambda: self._send_gcode_command("G28"))

        control_layout.addWidget(btn_m17, 2, 0)
        control_layout.addWidget(btn_m18, 2, 1)
        control_layout.addWidget(btn_m112, 2, 2)
        control_layout.addWidget(btn_g28, 3, 0)

        btn_g90 = QPushButton("G90 (Absolute)")
        btn_g90.clicked.connect(lambda: self._send_gcode_command("G90"))
        btn_g91 = QPushButton("G91 (Relative)")
        btn_g91.clicked.connect(lambda: self._send_gcode_command("G91"))
        self.cb_g92_axis = QComboBox()
        self.cb_g92_axis.addItems(["R", "T", "Z", "X", "Y", "A"])
        btn_g92 = QPushButton("G92 Zero Axis")
        btn_g92.clicked.connect(self._send_g92_zero)
        control_layout.addWidget(btn_g90, 3, 1)
        control_layout.addWidget(btn_g91, 3, 2)
        control_layout.addWidget(QLabel("G92 Axis:"), 4, 0)
        control_layout.addWidget(self.cb_g92_axis, 4, 1)
        control_layout.addWidget(btn_g92, 4, 2)

        control_group.setLayout(control_layout)
        layout.addWidget(control_group)

        projector_group = QGroupBox("Projector Control")
        proj_layout = QHBoxLayout()
        proj_cmds = [
            ("M200 On", "M200"),
            ("M201 Off", "M201"),
            ("M202 Play", "M202"),
            ("M203 Pause", "M203"),
            ("M204 Restart", "M204"),
        ]
        for label_text, cmd in proj_cmds:
            btn = QPushButton(label_text)
            btn.clicked.connect(lambda checked=False, c=cmd: self._send_gcode_command(c))
            proj_layout.addWidget(btn)
        projector_group.setLayout(proj_layout)
        layout.addWidget(projector_group)

        seq_group = QGroupBox("Sequences")
        seq_layout = QHBoxLayout()
        btn_start_seq = QPushButton("Run Start Sequence")
        btn_start_seq.clicked.connect(self._send_start_sequence)
        btn_end_seq = QPushButton("Run End Sequence")
        btn_end_seq.clicked.connect(self._send_end_sequence)
        seq_layout.addWidget(btn_start_seq)
        seq_layout.addWidget(btn_end_seq)
        seq_group.setLayout(seq_layout)
        layout.addWidget(seq_group)

        custom_group = QGroupBox("Custom Command")
        custom_layout = QHBoxLayout()
        self.le_custom_cmd = QLineEdit()
        self.le_custom_cmd.setPlaceholderText("e.g., G4 P10")
        btn_custom = QPushButton("Send")
        btn_custom.clicked.connect(self._send_custom_command)
        custom_layout.addWidget(self.le_custom_cmd, 1)
        custom_layout.addWidget(btn_custom)
        custom_group.setLayout(custom_layout)
        layout.addWidget(custom_group)

        jog_group = QGroupBox("Jog Control")
        jog_layout = QGridLayout()
        self.le_jog_step = QDoubleSpinBox(); self.le_jog_step.setDecimals(3); self.le_jog_step.setRange(0.001, 10000.0); self.le_jog_step.setValue(1.0); self.le_jog_step.setSuffix(" mm")
        self.le_jog_feed = QDoubleSpinBox(); self.le_jog_feed.setDecimals(1); self.le_jog_feed.setRange(0.1, 100000.0); self.le_jog_feed.setValue(50.0); self.le_jog_feed.setSuffix(" mm/s")
        jog_layout.addWidget(QLabel("Step Size:"), 0, 0)
        jog_layout.addWidget(self.le_jog_step, 0, 1)
        jog_layout.addWidget(QLabel("Jog Speed:"), 0, 2)
        jog_layout.addWidget(self.le_jog_feed, 0, 3)

        btn_r_minus = QPushButton("-R")
        btn_r_minus.clicked.connect(lambda: self._send_jog("R", -1))
        btn_r_plus = QPushButton("+R")
        btn_r_plus.clicked.connect(lambda: self._send_jog("R", 1))
        btn_t_minus = QPushButton("-T")
        btn_t_minus.clicked.connect(lambda: self._send_jog("T", -1))
        btn_t_plus = QPushButton("+T")
        btn_t_plus.clicked.connect(lambda: self._send_jog("T", 1))
        btn_z_minus = QPushButton("-Z")
        btn_z_minus.clicked.connect(lambda: self._send_jog("Z", -1))
        btn_z_plus = QPushButton("+Z")
        btn_z_plus.clicked.connect(lambda: self._send_jog("Z", 1))

        jog_layout.addWidget(btn_r_minus, 1, 0)
        jog_layout.addWidget(btn_r_plus, 1, 1)
        jog_layout.addWidget(btn_t_minus, 1, 2)
        jog_layout.addWidget(btn_t_plus, 1, 3)
        jog_layout.addWidget(btn_z_minus, 2, 0)
        jog_layout.addWidget(btn_z_plus, 2, 1)

        jog_group.setLayout(jog_layout)
        layout.addWidget(jog_group)

        self.txt_gcode_log = QTextEdit()
        self.txt_gcode_log.setReadOnly(True)
        log_header = QHBoxLayout()
        log_header.addWidget(QLabel("G-code Console"))
        btn_save_log = QPushButton("Save Output")
        btn_save_log.clicked.connect(self._save_gcode_log)
        log_header.addStretch(1)
        log_header.addWidget(btn_save_log)
        layout.addLayout(log_header)
        layout.addWidget(self.txt_gcode_log, 1)

        self.tabs.addTab(tab, "G-Code")

    def _append_gcode_log(self, msg: str):
        if hasattr(self, "txt_gcode_log") and self.txt_gcode_log:
            self.txt_gcode_log.append(msg)

    def _ensure_remote_ready(self) -> bool:
        if not self._ssh_worker or not self._ssh_connected:
            QMessageBox.warning(self, "SSH", "Connect to the Jetson before sending G-code.")
            return False
        return True

    def _send_gcode_command(self, command: str):
        command = command.strip()
        if not command:
            return
        if not self._ensure_remote_ready():
            return
        self._append_gcode_log(f"> {command}")
        try:
            self._ssh_worker.enqueue_command(command)
        except Exception as exc:
            self._append_gcode_log(f"[LOCAL] Failed to queue command: {exc}")

    def _collect_feedrates(self):
        parts = []
        for prefix, widget in (("FR", self.le_g1_fr), ("FT", self.le_g1_ft), ("FZ", self.le_g1_fz)):
            val = widget.text().strip()
            if val:
                parts.append(f"{prefix}{val}")
        return parts

    def _send_axis_command(self, base, axis_widgets, extra_parts=None):
        parts = [base]
        for axis, widget in axis_widgets.items():
            val = widget.text().strip()
            if val:
                parts.append(f"{axis}{val}")
        if extra_parts:
            parts.extend(extra_parts)
        if len(parts) == 1:
            QMessageBox.warning(self, base, "Enter at least one axis value.")
            return
        self._send_gcode_command(" ".join(parts))

    def _send_g4_wait(self):
        seconds = self.sb_g4_wait.value()
        self._send_gcode_command(f"G4 P{seconds}")

    def _send_g92_zero(self):
        axis = self.cb_g92_axis.currentText()
        self._send_gcode_command(f"G92 {axis}")

    def _send_custom_command(self):
        cmd = self.le_custom_cmd.text()
        self._send_gcode_command(cmd)
        self.le_custom_cmd.clear()

    def _save_gcode_log(self):
        if not self.txt_gcode_log:
            return
        default_path = Path.home() / "gcode_output.txt"
        fname, _ = QFileDialog.getSaveFileName(
            self,
            "Save G-code Output",
            str(default_path),
            "Text Files (*.txt);;All Files (*.*)",
        )
        if not fname:
            return
        try:
            Path(fname).write_text(self.txt_gcode_log.toPlainText(), encoding="utf-8")
            QMessageBox.information(self, "Saved", f"G code output saved to:\n{fname}")
        except Exception as exc:
            QMessageBox.critical(self, "Save Failed", f"Could not save log: {exc}")

    def _send_jog(self, axis: str, direction: int):
        if not self._ensure_remote_ready():
            return
        step = float(self.le_jog_step.value()) if self.le_jog_step else 0.0
        feed = float(self.le_jog_feed.value()) if self.le_jog_feed else 0.0
        if step <= 0 or feed <= 0:
            QMessageBox.warning(self, "Jog", "Set a positive step size and jog speed.")
            return
        delta = step * direction
        commands = [
            "G91",
            f"G1 {axis}{delta} F{feed}",
            "G90",
        ]
        for cmd in commands:
            self._send_gcode_command(cmd)

    def _send_start_sequence(self):
        g0_cmd = self._build_axis_command_for_sequence()
        if not g0_cmd:
            QMessageBox.warning(self, "Start Sequence", "Provide at least one axis value in the G0 row for the start sequence.")
            return
        commands = [
            "M17",
            "G28",
            g0_cmd,
            "G92",
            "G33 A9",
            "G5",
        ]
        for cmd in commands:
            self._send_gcode_command(cmd)

    def _send_end_sequence(self):
        commands = ["G33 A0", "G28", "M18"]
        for cmd in commands:
            self._send_gcode_command(cmd)

    def _build_axis_command_for_sequence(self):
        axis_widgets = {"R": self.le_g0_r, "T": self.le_g0_t, "Z": self.le_g0_z}
        parts = ["G0"]
        for axis, widget in axis_widgets.items():
            val = widget.text().strip()
            if val:
                parts.append(f"{axis}{val}")
        if len(parts) == 1:
            return None
        return " ".join(parts)

    def closeEvent(self, event):
        self._shutdown_ssh_worker()
        super().closeEvent(event)


def main():
    app = QApplication(sys.argv)
    w = HeliCALQt()
    w.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
