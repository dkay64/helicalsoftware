import os
import cv2
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton
from PyQt5.QtGui import QImage, QPixmap
from PyQt5.QtCore import Qt, QThread, pyqtSignal

class VideoStreamWorker(QThread):
    change_pixmap_signal = pyqtSignal(QImage)

    def __init__(self, rtsp_url, parent=None):
        super().__init__(parent)
        self.rtsp_url = rtsp_url
        self._is_running = True

    def run(self):
        # LOW LATENCY FLAGS
        os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = (
            "rtsp_transport;tcp|probesize;32|analyzeduration;0|fflags;nobuffer|flags;low_delay|hwaccel;videotoolbox"
        )
        cap = None
        for i in range(5):
            if not self._is_running: return
            cap = cv2.VideoCapture(self.rtsp_url, cv2.CAP_FFMPEG)
            if cap.isOpened():
                break
            cap.release()
            print(f"Attempt {i+1}: Stream not ready, retrying...")
            self.msleep(1500)

        if not cap or not cap.isOpened():
            print("Failed to connect after 5 attempts.")
            return

        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        while self._is_running and cap.isOpened():
            if not cap.grab():
                break
                
            ret, cv_img = cap.retrieve()

            if ret:
                rgb_image = cv2.cvtColor(cv_img, cv2.COLOR_BGR2RGB)
                h, w, ch = rgb_image.shape
                qt_image = QImage(rgb_image.data, w, h, ch * w, QImage.Format_RGB888)
                
                scaled_image = qt_image.scaledToHeight(720, Qt.SmoothTransformation) 
                self.change_pixmap_signal.emit(scaled_image)
            
        cap.release()

    def stop(self):
        self._is_running = False
        self.wait()

class EmbeddedVideoWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        
        self.image_label = QLabel(self)
        self.image_label.setAlignment(Qt.AlignCenter)
        
        self.layout.addStretch()
        self.layout.addWidget(self.image_label)
        self.layout.addStretch()
        
        self.worker = None
        self.set_offline_style()

    def set_offline_style(self):
        self.image_label.clear()
        self.image_label.setText("CAMERA OFFLINE")
        
        self.image_label.setFixedSize(960, 720) # Changed from 960, 720
        self.image_label.setStyleSheet(
            "background-color: #000000; color: #71717a; font-weight: bold; font-size: 24px; border-radius: 12px;"
        )

    def play(self, url):
        self.stop() 
        self.image_label.clear()
        self.worker = VideoStreamWorker(url)
        self.worker.change_pixmap_signal.connect(self.update_image)
        self.worker.start()

    def update_image(self, qt_img):
        pixmap = QPixmap.fromImage(qt_img)
        self.image_label.setPixmap(pixmap)
        self.image_label.setFixedSize(pixmap.size())

    def stop(self):
        if self.worker:
            try:
                self.worker.change_pixmap_signal.disconnect()
            except:
                pass
            self.worker.stop()
            self.worker = None
        self.set_offline_style()

class MetrologyPage(QWidget):
    log_message = pyqtSignal(str, str)

    def __init__(self, main_window=None, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        
        # Use a local variable for the layout to avoid PyQt conflicts
        main_layout = QVBoxLayout(self)
        self.button_layout = QHBoxLayout()
        
        self.start_btn = QPushButton("Turn Feed ON")
        self.start_btn.setStyleSheet("background-color: #22c55e; color: white; font-weight: bold; padding: 15px; font-size: 16pt;")
        
        self.stop_btn = QPushButton("Turn Feed OFF")
        self.stop_btn.setStyleSheet("background-color: #ef4444; color: white; font-weight: bold; padding: 15px; font-size: 16pt;")
        self.stop_btn.setEnabled(False)
        
        self.button_layout.addWidget(self.start_btn)
        self.button_layout.addWidget(self.stop_btn)
        main_layout.addLayout(self.button_layout)
        self.camera_view = EmbeddedVideoWidget()
        main_layout.addWidget(self.camera_view)
        main_layout.addStretch()
        self.start_btn.clicked.connect(self.start_feed)
        self.stop_btn.clicked.connect(self.stop_feed)

    def start_feed(self):
        rtsp_url = "rtsp://192.168.0.116:8554/cam" 
        self.camera_view.play(rtsp_url)
        
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.log_message.emit("Started metrology feed.", "INFO")

    def stop_feed(self):
        self.camera_view.stop()
        
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.log_message.emit("Stopped metrology feed.", "INFO")