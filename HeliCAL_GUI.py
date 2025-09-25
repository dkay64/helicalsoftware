import sys
import subprocess
import threading
import time

from PyQt5.QtCore import QTimer, Qt
from PyQt5.QtWidgets import QApplication, QMainWindow, QWidget, QTabWidget, QVBoxLayout, QPushButton, QFileDialog, QLabel, QHBoxLayout, QLineEdit, QTextEdit, QMessageBox
from PyQt5.QtGui import QImage, QPixmap
import serial
import cv2

class HeliCALGui(QMainWindow):
    """
    Main GUI for the HeliCAL Control Panel.

    This class builds a tabbed interface with buttons and controls for running calibration, rotation, printing, balancing, and camera feed.
    """
    def __init__(self):
        super().__init__()
        """
        Initialize the main window, state variables, and all UI tabs.

        Sets up:
        - Window title and default size
        - Serial port placeholder (for ESP32 connection)
        - Camera capture placeholder
        - Tab widget and calls individual builders
        """
        self.setWindowTitle("HeliCAL Control Panel")
        self.resize(800, 600)

        # Placeholder for serial communication and camera stream
        self.serial_port = None
        self.camera = None

        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)

        self._build_calibration_tab()
        self._build_rotation_tab()
        self._build_print_tab()
        self._build_balance_tab()
        self._build_camera_tab()

    def _build_calibration_tab(self):
        """
        Create the 'Calibration' tab.

        Adds a button that launches the external calibration executable:
        Assumes 'cal6_calibrate' is in your system PATH or working directory.
        """
        tab = QWidget()
        layout = QVBoxLayout()

        btn_calibrate = QPushButton("Run Calibration (cal6_calibrate)")
        btn_calibrate.clicked.connect(self.run_calibration)
        layout.addWidget(btn_calibrate)

        tab.setLayout(layout)
        self.tabs.addTab(tab, "Calibration")

    def _build_rotation_tab(self):
        """
        Create the 'Rotation' tab.

        Provides:
        - A QLineEdit to specify the serial port (default '/dev/ttyTHS1').
        - A button to connect to the ESP32 over UART at 115200 baud.
        - Buttons to start (9 RPM) and stop rotation by sending velocity commands.
        """
        tab = QWidget()
        layout = QVBoxLayout()

        # serial port entry and connect button
        hbox = QHBoxLayout()
        self.port_input = QLineEdit("/dev/ttyTHS1") # Default Jetson UART port
        btn_connect = QPushButton("Connect ESP32")
        btn_connect.clicked.connect(self.connect_esp32)
        hbox.addWidget(QLabel("Serial Port:"))
        hbox.addWidget(self.port_input)
        hbox.addWidget(btn_connect)
        layout.addLayout(hbox)

        btn_start = QPushButton("Start Rotation (9 RPM)")
        btn_start.clicked.connect(lambda: self.send_theta_velocity(9))
        btn_stop = QPushButton("Stop Rotation")
        btn_stop.clicked.connect(lambda: self.send_theta_velocity(0))
        layout.addWidget(btn_start)
        layout.addWidget(btn_stop)

        tab.setLayout(layout)
        self.tabs.addTab(tab, "Rotation")

    def _build_print_tab(self):
        """
        Create the 'Print' tab.

        Enables:
        - Selecting an MP4 video file via file dialog.
        - Launching the multi-pass z-translation print executable with arguments.
        """
        tab = QWidget()
        layout = QVBoxLayout()

        btn_select_video = QPushButton("Select Video File")
        btn_select_video.clicked.connect(self.select_video)
        layout.addWidget(btn_select_video)
        self.video_path = QLineEdit() # Display selected file path
        layout.addWidget(self.video_path)

        btn_print = QPushButton("Start Z-Translation Multi-Pass Print")
        btn_print.clicked.connect(self.run_print)
        layout.addWidget(btn_print)

        tab.setLayout(layout)
        self.tabs.addTab(tab, "Print")

    def _build_balance_tab(self):
        """
        Create the 'Balancing' tab.

        Adds a button to start the real-time balancing routine.
        Expects './cal6_balance' executable available.
        """
        tab = QWidget()
        layout = QVBoxLayout()

        btn_balance = QPushButton("Start Real-Time Balancing")
        btn_balance.clicked.connect(self.run_balancing)
        layout.addWidget(btn_balance)

        tab.setLayout(layout)
        self.tabs.addTab(tab, "Balancing")

    def _build_camera_tab(self):
        """
        Create the 'Camera' tab.

        Shows live video feed from the default camera (index 0).
        Includes:
        - QLabel for image display
        - Button to open camera and begin frame updates
        - QTimer to refresh frames at regular intervals
        """
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

    def run_calibration(self):
        """
        Launch the calibration executable in a separate thread.

        Uses subprocess.run to call './cal6_calibrate'.
        Runs detached to avoid blocking the UI.
        """
        threading.Thread(target=lambda: subprocess.run(['./cal6_calibrate'], check=True)).start()

    def connect_esp32(self):
        port = self.port_input.text().strip()
        try:
            self.serial_port = serial.Serial(port, 115200, timeout=0.1)
            QMessageBox.information(self, "ESP32", f"Connected to {port}")
        except Exception as e:
            QMessageBox.critical(self, "ESP32", f"Failed to open {port}: {e}")

    def send_theta_velocity(self, rpm):
        if not self.serial_port:
            QMessageBox.warning(self, "ESP32", "Connect to ESP32 first.")
            return
        # velocity in encoder counts/sec: 245426 * rpm / 60
        velocity = int(245426 * rpm / 60)
        cmd = bytearray([0x20, 0x20]) + velocity.to_bytes(4, 'little', signed=True)
        self.serial_port.write(cmd)

    def select_video(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select MP4 Video", "", "Video Files (*.mp4)")
        if path:
            self.video_path.setText(path)

    def run_print(self):
        video = self.video_path.text().strip()
        if not video:
            QMessageBox.warning(self, "Print", "Select a video file first.")
            return
        cmd = ['./cal6_print_z_translation_multi_pass', video, 'output.mp4',
               '--crop_height_px', '800', '--cycles_per_pass', '1', '--deg_per_sec', '9']
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