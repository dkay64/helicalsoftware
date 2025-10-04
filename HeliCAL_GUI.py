import sys
import subprocess
import threading
import time

from PyQt5.QtCore import QTimer, Qt
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QTabWidget, QVBoxLayout, QPushButton,
    QFileDialog, QLabel, QHBoxLayout, QLineEdit, QTextEdit, QMessageBox
)
from PyQt5.QtGui import QImage, QPixmap
import serial
import cv2

class HeliCALGui(QMainWindow):
    """
    Main GUI for the HeliCAL Control Panel.
    """
    def __init__(self):
        super().__init__()
        self.setWindowTitle("HeliCAL Control Panel")
        self.resize(800, 600)

        # Placeholders for serial & camera
        self.serial_port = None
        self.camera = None

        # Runtime-configurable counts per theta revolution (default from system inference)
        self.counts_per_theta_rev = 245426  # editable in UI

        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)

        self._build_calibration_tab()
        self._build_rotation_tab()
        self._build_print_tab()
        self._build_balance_tab()
        self._build_camera_tab()

    # ---------------- Tabs ----------------
    def _build_calibration_tab(self):
        tab = QWidget()
        layout = QVBoxLayout()

        btn_calibrate = QPushButton("Run Calibration (cal6_calibrate)")
        btn_calibrate.clicked.connect(self.run_calibration)
        layout.addWidget(btn_calibrate)

        tab.setLayout(layout)
        self.tabs.addTab(tab, "Calibration")

    def _build_rotation_tab(self):
        tab = QWidget()
        layout = QVBoxLayout()

        # Serial connect row
        hbox1 = QHBoxLayout()
        self.port_input = QLineEdit("/dev/ttyTHS1")
        btn_connect = QPushButton("Connect ESP32")
        btn_connect.clicked.connect(self.connect_esp32)
        hbox1.addWidget(QLabel("Serial Port:"))
        hbox1.addWidget(self.port_input)
        hbox1.addWidget(btn_connect)
        layout.addLayout(hbox1)

        # Counts-per-rev row (editable)
        hbox2 = QHBoxLayout()
        self.cpr_input = QLineEdit(str(self.counts_per_theta_rev))
        hbox2.addWidget(QLabel("Counts per θ-rev:"))
        hbox2.addWidget(self.cpr_input)
        layout.addLayout(hbox2)

        # Controls
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

        self.timer = QTimer()
        self.timer.timeout.connect(self.update_frame)

    # ---------------- Helpers ----------------
    def run_calibration(self):
        threading.Thread(target=lambda: subprocess.run(['./cal6_calibrate'], check=True)).start()

    def connect_esp32(self):
        port = self.port_input.text().strip()
        try:
            self.serial_port = serial.Serial(port, 115200, timeout=0.2)
            QMessageBox.information(self, "ESP32", f"Connected to {port}")
        except Exception as e:
            QMessageBox.critical(self, "ESP32", f"Failed to open {port}: {e}")

    def rpm_to_pulses_per_sec(self, rpm: float) -> int:
        """
        Convert rpm on the theta axis to encoder pulses/sec using counts_per_theta_rev.
        pulses/sec = rpm * counts_per_theta_rev / 60
        """
        try:
            # Refresh from UI (allows live edits)
            self.counts_per_theta_rev = int(float(self.cpr_input.text().strip()))
        except Exception:
            self.counts_per_theta_rev = 245426
            self.cpr_input.setText(str(self.counts_per_theta_rev))

        return int(round((rpm * self.counts_per_theta_rev) / 60.0))

    # ---- NEW: velocity command using 0x30/0x01 (THETA_VEL_SET) ----
    def send_theta_velocity_rpm(self, rpm: float):
        """
        Sends a closed-loop velocity command to firmware:
          [0x30, 0x01, <int32_le pulses/sec>]
        """
        if not self.serial_port:
            QMessageBox.warning(self, "ESP32", "Connect to ESP32 first.")
            return

        # Convert rpm -> pulses/sec
        pps = self.rpm_to_pulses_per_sec(rpm)

        # Build command (6 bytes total)
        cmd = bytearray([0x30, 0x01]) + int(pps).to_bytes(4, 'little', signed=True)

        try:
            # Optional: clear any stale bytes then send
            self.serial_port.reset_input_buffer()
            self.serial_port.write(cmd)
            self.serial_port.flush()

            # Optional: read 1-byte ACK (firmware writes back a single 0x01)
            ack = self.serial_port.read(1)
            # You can log/ignore ack; not fatal if missing due to timing
        except Exception as e:
            QMessageBox.critical(self, "UART", f"Failed to send velocity: {e}")

    # ---------------- Print / Balance / Camera ----------------
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
            './cal6_print_z_translation_multi_pass', video, 'output.mp4',
            '--crop_height_px', '800', '--cycles_per_pass', '1', '--deg_per_sec', '9'
        ]
        threading.Thread(target=lambda: subprocess.run(cmd, check=True)).start()

    def run_balancing(self):
        threading.Thread(target=lambda: subprocess.run(['./cal6_balance'], check=True)).start()

    def open_camera(self):
        self.camera = cv2.VideoCapture(0)
        if not self.camera.isOpened():
            QMessageBox.critical(self, "Camera", "Failed to open camera.")
            return
        self.timer.start(30)

    def update_frame(self):
        ret, frame = self.camera.read()
        if not ret:
            return
        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, ch = frame.shape
        bytes_per_line = ch * w
        img = QImage(frame.data, w, h, bytes_per_line, QImage.Format_RGB888)
        self.lbl_camera.setPixmap(QPixmap.fromImage(img).scaled(
            self.lbl_camera.size(), Qt.KeepAspectRatio
        ))

if __name__ == '__main__':
    app = QApplication(sys.argv)
    gui = HeliCALGui()
    gui.show()
    sys.exit(app.exec_())
