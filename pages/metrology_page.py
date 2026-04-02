import os
import cv2
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton
from PyQt5.QtGui import QImage, QPixmap
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer
import paramiko
from PyQt5.QtCore import QTimer, pyqtSignal, Qt, QThread
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton

class JetsonController(QThread):
    ui_status_update = pyqtSignal(str)
    log_update = pyqtSignal(str, str)
    ready_to_connect = pyqtSignal()

    def run(self):
        self.ui_status_update.emit("SSHing INTO JETSON...")
        self.log_update.emit("Initiating SSH connection to jacob@192.168.0.116...", "INFO")
        QThread.msleep(500)
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        
        try:
            # Connect with the password explicitly
            ssh.connect('192.168.0.116', username='jacob', password='helical', timeout=5)
            self.log_update.emit("SSH connection successful.", "SUCCESS")
            
            self.ui_status_update.emit("STARTING CAMERA SCRIPT...")
            self.log_update.emit("Running: ./start_camera_stream.sh", "INFO")
            stdin, stdout, stderr = ssh.exec_command(
                "cd Desktop && nohup ./start_camera_stream.sh > stream.log 2>&1 &"
            )
            
            # Wait a few seconds for GStreamer to fully warm up the camera hardware
            QThread.msleep(3000)
            self.log_update.emit("Camera script executed. RTSP server should be online.", "INFO")
            
        except Exception as e:
            self.log_update.emit(f"Failed to start Jetson stream: {str(e)}", "ERROR")
            self.ui_status_update.emit("CONNECTION FAILED")
            return 
            
        finally:
            # Always close the connection nicely
            ssh.close()

        # --- Trigger Video Connection ---
        self.ui_status_update.emit("CONNECTING TO STREAM...")
        self.ready_to_connect.emit()

class JetsonStopController(QThread):
    ui_status_update = pyqtSignal(str)
    log_update = pyqtSignal(str, str)
    finished_stopping = pyqtSignal()

    def run(self):
        self.ui_status_update.emit("SHUTTING DOWN CAMERA...")
        self.log_update.emit("Connecting to Jetson to kill feed...", "INFO")
        
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        
        try:
            ssh.connect('192.168.0.116', username='jacob', password='helical', timeout=5)
            
            # The 3 commands chained together. 
            # We use gst-launch-1.0 here because that's what your bash script uses!
            kill_commands = (
                "pkill -f start_camera_stream.sh; "
                "pkill -f gst-launch-1.0; "
                "echo 'helical' | sudo -S systemctl restart nvargus-daemon"
            )
            
            stdin, stdout, stderr = ssh.exec_command(kill_commands)
            
            # Wait for the terminal to finish executing before closing
            exit_status = stdout.channel.recv_exit_status() 
            
            self.log_update.emit("Camera feed stopped and hardware reset.", "SUCCESS")
            
        except Exception as e:
            self.log_update.emit(f"Failed to cleanly stop Jetson: {str(e)}", "ERROR")
            
        finally:
            ssh.close()
            self.finished_stopping.emit()

class VideoStreamWorker(QThread):
    change_pixmap_signal = pyqtSignal(QImage)

    def __init__(self, rtsp_url):
        super().__init__()
        self.rtsp_url = rtsp_url
        self._is_running = True

    def run(self):
        os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"
        
        while self._is_running:
            cap = cv2.VideoCapture(self.rtsp_url, cv2.CAP_FFMPEG)
            
            if cap.isOpened():
                print("Stream connected!")
                
                # As long as the stream is open and we haven't hit STOP, read frames
                while self._is_running and cap.isOpened():
                    ret, frame = cap.read()
                    if ret:
                        rgb_image = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                        h, w, ch = rgb_image.shape
                        qt_image = QImage(rgb_image.data, w, h, ch * w, QImage.Format_RGB888)
                        scaled_image = qt_image.scaledToHeight(720, Qt.SmoothTransformation)
                        self.change_pixmap_signal.emit(scaled_image)
                    else:
                        break # The stream dropped, break out to reconnect
            
            # Clean up the capture object before trying again
            if cap:
                cap.release()
            
            # If the user hit STOP, exit the thread completely
            if not self._is_running:
                break
                
            # If we are here, the stream wasn't ready (404) or it dropped. 
            # Wait 1 second and try again. No limits, no crashing.
            print("Looking for stream...")
            self.msleep(1000) 

    def stop(self):
        self._is_running = False
        self.wait()

class MetrologyPage(QWidget):
    # Add the signal back so main_window can connect to it!
    log_message = pyqtSignal(str, str)

    def __init__(self, main_window=None, parent=None):
        super().__init__(parent)
        self.main_window = main_window # Store the main window reference
        
        layout = QVBoxLayout(self)
        
        # --- Buttons ---
        btn_layout = QHBoxLayout()
        self.start_btn = QPushButton("Turn Feed ON")
        self.start_btn.setStyleSheet("background-color: #22c55e; color: white; font-weight: bold; padding: 15px; font-size: 16pt;")
        
        self.stop_btn = QPushButton("Turn Feed OFF")
        self.stop_btn.setStyleSheet("background-color: #ef4444; color: white; font-weight: bold; padding: 15px; font-size: 16pt;")
        self.stop_btn.setEnabled(False)
        
        btn_layout.addWidget(self.start_btn)
        btn_layout.addWidget(self.stop_btn)
        layout.addLayout(btn_layout)
        
        # --- Video Display ---
        self.image_label = QLabel("CAMERA OFFLINE")
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setFixedSize(960, 720)
        self.image_label.setStyleSheet("background-color: #000000; color: #71717a; font-weight: bold; font-size: 24px; border-radius: 12px;")
        
        layout.addStretch()
        layout.addWidget(self.image_label, alignment=Qt.AlignCenter)
        layout.addStretch()
        
        # --- Connections ---
        self.start_btn.clicked.connect(self.start_feed)
        self.stop_btn.clicked.connect(self.stop_feed)
        self.worker = None

    def start_feed(self):
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        
        # Initialize the controller and connect its reporting signals to our GUI!
        self.jetson = JetsonController()
        
        # When JetsonController emits a UI update, change the big label text
        self.jetson.ui_status_update.connect(self.image_label.setText)
        
        # When JetsonController emits a log update, forward it to the main log
        self.jetson.log_update.connect(self.log_message.emit)
        
        # When JetsonController finishes booting the camera, start the video worker!
        self.jetson.ready_to_connect.connect(self.start_video_worker)
        
        # Kick off the process
        self.jetson.start()

    def start_video_worker(self):
        """Called automatically when JetsonController says the stream is ready."""
        self.log_message.emit("Opening RTSP stream in OpenCV...", "INFO")
        
        self.worker = VideoStreamWorker("rtsp://192.168.0.116:8554/cam")
        self.worker.change_pixmap_signal.connect(self.update_image)
        self.worker.start()

    def update_image(self, qt_img):
        self.image_label.setPixmap(QPixmap.fromImage(qt_img))

    def stop_feed(self):
        # Disable both buttons while we safely shut down
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(False)
        
        # 1. Instantly stop the PyQt video worker so it doesn't freeze looking for a dead stream
        if self.worker:
            self.worker.change_pixmap_signal.disconnect()
            self.worker.stop()
            self.worker = None
            
        self.image_label.clear()
        
        # 2. Fire up the thread to run the kill commands
        self.stop_thread = JetsonStopController()
        self.stop_thread.ui_status_update.connect(self.image_label.setText)
        self.stop_thread.log_update.connect(self.log_message.emit)
        self.stop_thread.finished_stopping.connect(self.on_feed_stopped)
        self.stop_thread.start()

    def on_feed_stopped(self):
        """Called automatically when the JetsonStopController finishes."""
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.image_label.setText("CAMERA OFFLINE")