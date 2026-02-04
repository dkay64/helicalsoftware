import sys
import random
import os
from PyQt5.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QFrame,
    QMessageBox,
    QGridLayout,
    QStackedWidget,
)
from PyQt5.QtGui import QFont, QIcon, QPixmap
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer, QTime, QSize, QUrl
from PyQt5.QtMultimediaWidgets import QVideoWidget
from PyQt5.QtMultimedia import QMediaPlayer, QMediaContent


# --- Constants and Styling ---
STYLESHEET = """
    #DisplayPage {
        background-color: #09090b;
        color: #e4e4e7;
    }
    /* --- Video Widgets --- */
    .VideoContainer {
        min-height: 320px;
        max-width: 800px;
        background-color: black;
        border-radius: 12px;
    }
    #CameraPlaceholder {
        min-height: 320px;
        max-width: 800px;
        background-color: #18181b;
        border: 1px solid #27272a;
        border-radius: 12px;
        color: #71717a;
        font-size: 14pt;
        font-weight: bold;
    }
    #VideoFeedLabel {
        font-size: 11pt;
        font-weight: bold;
        color: #a1a1aa;
        padding-bottom: 5px;
    }
    #VideoStatusLabel {
        font-size: 14pt;
        color: #a1a1aa;
    }

    /* --- Sensor Card --- */
    .SensorCard {
        background-color: #18181b;
        border: 1px solid #2a2724;
        border-radius: 8px;
    }
    .CardIconPlaceholder {
        min-width: 24px;
        max-width: 24px;
        min-height: 24px;
        max-height: 24px;
        background-color: #3f3f46;
        border-radius: 4px;
    }
    .CardTitle { font-size: 14pt; font-weight: bold; color: #fafafa; }
    .SensorLabel, .SensorTarget { font-size: 11pt; color: #a1a1aa; }
    .SensorActual {
        font-size: 16pt;
        font-weight: bold;
        color: #22c55e;
        font-family: 'Consolas', 'Monospace';
    }
    .GridHeader { font-size: 9pt; font-weight: bold; color: #71717a; }

    /* --- Footer Controls --- */
    #TimerLabel { font-size: 28pt; font-weight: bold; color: #fafafa; }
    #EndPrintButton {
        background-color: #991b1b;
        color: #fafafa;
        font-weight: bold;
        font-size: 12pt;
        border: 1px solid #7f1d1d;
        border-radius: 6px;
        padding: 10px;
    }
    #EndPrintButton:hover { background-color: #b91c1c; }
"""

class SensorWorker(QThread):
    data_updated = pyqtSignal(dict)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._is_running = True

    def run(self):
        while self._is_running:
            data = {
                'cw_r': random.uniform(0.0, 100.0), 'cw_t': random.uniform(-180.0, 180.0), 'cw_z': random.uniform(0.0, 50.0),
                'tw_r': random.uniform(0.0, 100.0), 'tw_t': random.uniform(-180.0, 180.0), 'tw_z': random.uniform(0.0, 50.0),
                'rpm': random.uniform(500.0, 600.0),
                'imu_ax': random.uniform(-1.0, 1.0), 'imu_ay': random.uniform(-1.0, 1.0), 'imu_az': random.uniform(9.5, 10.1),
            }
            self.data_updated.emit(data)
            self.msleep(100)

    def stop(self):
        if self.isRunning():
            self._is_running = False
            self.wait()

class SensorCard(QFrame):
    def __init__(self, title, icon_path, parameters, label_map, log_signal, parent=None):
        super().__init__(parent)
        self.setProperty("class", "SensorCard")
        self.log_message = log_signal
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(15, 10, 15, 15)
        main_layout.setSpacing(10)

        header_layout = QHBoxLayout()
        icon = QIcon(icon_path)
        if icon.isNull():
            self.log_message.emit(f"Could not load icon '{icon_path}'. Using fallback.", "WARNING")
            icon_widget = QFrame()
            icon_widget.setProperty("class", "CardIconPlaceholder")
        else:
            icon_widget = QLabel()
            icon_pixmap = icon.pixmap(QSize(24, 24))
            icon_widget.setPixmap(icon_pixmap)
        
        header_layout.addWidget(icon_widget)
        header_layout.addWidget(QLabel(title, objectName="CardTitle"))
        header_layout.addStretch()
        main_layout.addLayout(header_layout)

        grid_layout = QGridLayout()
        grid_layout.setSpacing(8)
        grid_layout.setHorizontalSpacing(40) # Increase gap between columns
        grid_layout.setColumnStretch(0, 1)
        grid_layout.setColumnMinimumWidth(1, 70)

        self.param_labels = {}
        target_header = QLabel("TARGET")
        target_header.setProperty("class", "GridHeader")
        target_header.setAlignment(Qt.AlignRight)
        
        actual_header = QLabel("ACTUAL")
        actual_header.setProperty("class", "GridHeader")
        actual_header.setAlignment(Qt.AlignRight)
        actual_header.setFixedWidth(120)
        
        grid_layout.addWidget(target_header, 0, 1)
        grid_layout.addWidget(actual_header, 0, 2)

        # Force exactly 3 rows of data slots
        for i in range(3):
            row = i + 1 # Rows 1, 2, 3
            
            # Check if a real parameter exists for this row
            if i < len(parameters) and parameters[i] is not None:
                param_key = parameters[i]
                display_name = label_map.get(param_key, param_key.upper())
                label, target_val, actual_val = QLabel(display_name), QLabel("0.00"), QLabel("0.00")
                
                label.setProperty("class", "SensorLabel")
                target_val.setProperty("class", "SensorTarget")
                actual_val.setProperty("class", "SensorActual")
                
                target_val.setAlignment(Qt.AlignRight)
                actual_val.setAlignment(Qt.AlignRight)
                actual_val.setFixedWidth(120)

                grid_layout.addWidget(label, row, 0)
                grid_layout.addWidget(target_val, row, 1)
                grid_layout.addWidget(actual_val, row, 2)
                self.param_labels[param_key] = {'target': target_val, 'actual': actual_val}
            else:
                # Render a Dummy Row to preserve height
                dummy_label = QLabel(" ")
                dummy_label.setProperty("class", "SensorLabel") # Inherit style
                
                dummy_target = QLabel(" ")
                dummy_target.setProperty("class", "SensorTarget") # Inherit style
                dummy_target.setAlignment(Qt.AlignRight)

                dummy_actual = QLabel(" ")
                dummy_actual.setProperty("class", "SensorActual") # Inherit style
                dummy_actual.setFixedWidth(120)
                dummy_actual.setAlignment(Qt.AlignRight)

                grid_layout.addWidget(dummy_label, row, 0)
                grid_layout.addWidget(dummy_target, row, 1)
                grid_layout.addWidget(dummy_actual, row, 2)
            
        main_layout.addLayout(grid_layout)

    def update_values(self, data):
        for param_key, labels in self.param_labels.items():
            if param_key in data:
                labels['actual'].setText(f"{data[param_key]:.2f}")


class DisplayPage(QWidget):
    log_message = pyqtSignal(str, str)
    job_started = pyqtSignal()
    job_ended = pyqtSignal()

    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.setObjectName("DisplayPage")
        self.setStyleSheet(STYLESHEET)
        self.main_window = main_window
        
        self.media_player = None
        self.media_player_error = False

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 15, 20, 15)
        main_layout.setSpacing(15)

        timer_layout = QHBoxLayout()
        timer_layout.addStretch()
        self.timer_label = QLabel("00:00:00")
        self.timer_label.setObjectName("TimerLabel")
        timer_layout.addWidget(self.timer_label)
        timer_layout.addStretch()
        main_layout.addLayout(timer_layout)

        video_layout = QHBoxLayout()
        video_layout.setSpacing(20)
        video_layout.addStretch()
        video_layout.addLayout(self.create_reference_video_feed())
        video_layout.addLayout(self.create_camera_placeholder())
        video_layout.addStretch()
        main_layout.addLayout(video_layout)

        cards_layout = QGridLayout()
        cards_layout.setSpacing(20)
        
        cw_labels = {"cw_r": "R-Axis", "cw_t": "T-Axis", "cw_z": "Z-Axis"}
        rot_labels = {"rpm": "Speed (RPM)"}
        imu_labels = {"imu_ax": "Accel X", "imu_ay": "Accel Y", "imu_az": "Accel Z"}

        self.cw_card = SensorCard("Counterweight", "assets/icons/move-left.svg", ["cw_r", "cw_t", "cw_z"], cw_labels, self.log_message)
        self.tw_card = SensorCard("Twowave", "assets/icons/move-left.svg", ["cw_r", "cw_t", "tw_z"], cw_labels, self.log_message)
        self.rot_card = SensorCard("Rotating Stage", "assets/icons/repeat.svg", ["rpm", None, None], rot_labels, self.log_message)
        self.imu_card = SensorCard("IMU", "assets/icons/monitor.svg", ["imu_ax", "imu_ay", "imu_az"], imu_labels, self.log_message)
        
        cards_layout.addWidget(self.cw_card, 0, 0)
        cards_layout.addWidget(self.tw_card, 0, 1)
        cards_layout.addWidget(self.rot_card, 1, 0)
        cards_layout.addWidget(self.imu_card, 1, 1)
        main_layout.addLayout(cards_layout)
        main_layout.addStretch()

        footer_layout = QHBoxLayout()
        footer_layout.addStretch()
        self.end_print_button = QPushButton("End Print")
        self.end_print_button.setObjectName("EndPrintButton")
        self.end_print_button.setFixedWidth(200)
        self.end_print_button.clicked.connect(self.on_end_print_clicked)
        footer_layout.addWidget(self.end_print_button)
        main_layout.addLayout(footer_layout)

        self.job_time = QTime(0, 0, 0)
        self.job_timer = QTimer(self)
        self.job_timer.timeout.connect(self.update_timer)

        self.sensor_worker = SensorWorker(self)
        self.sensor_worker.data_updated.connect(self.update_cards)

    def create_reference_video_feed(self):
        feed_layout = QVBoxLayout()
        feed_layout.addWidget(QLabel("Reference Video", objectName="VideoFeedLabel"))

        # This QStackedWidget will act as a container, holding either the video
        # or a status label. We apply the 'VideoContainer' style to it directly.
        self.video_stack = QStackedWidget()
        self.video_stack.setProperty("class", "VideoContainer")

        # Page 0: The unstyled video widget. It will scale to fill the container.
        self.ref_video_widget = QVideoWidget()
        self.ref_video_widget.setAspectRatioMode(Qt.KeepAspectRatio)
        self.video_stack.addWidget(self.ref_video_widget)

        # Page 1: The status label for errors or missing files.
        self.ref_status_label = QLabel("No Signal", objectName="VideoStatusLabel")
        self.ref_status_label.setAlignment(Qt.AlignCenter)
        self.video_stack.addWidget(self.ref_status_label)

        feed_layout.addWidget(self.video_stack)
        return feed_layout

    def create_camera_placeholder(self):
        feed_layout = QVBoxLayout()
        feed_layout.addWidget(QLabel("Live Camera Feed", objectName="VideoFeedLabel"))
        
        placeholder = QLabel("LIVE FEED OFFLINE")
        placeholder.setObjectName("CameraPlaceholder")
        placeholder.setAlignment(Qt.AlignCenter)
        
        feed_layout.addWidget(placeholder)
        return feed_layout

    def set_video_source(self, file_path):
        if not self.media_player:
            self.media_player = QMediaPlayer(self, QMediaPlayer.VideoSurface)
            self.media_player.setVideoOutput(self.ref_video_widget)
            self.media_player.error.connect(self.handle_video_error)

        if file_path and os.path.exists(file_path):
            self.media_player.setMedia(QMediaContent(QUrl.fromLocalFile(file_path)))
            self.video_stack.setCurrentWidget(self.ref_video_widget)
            self.log_message.emit(f"Reference video loaded: {os.path.basename(file_path)}", "INFO")
        else:
            if self.media_player:
                self.media_player.stop()
            
            if file_path is None:
                self.ref_status_label.setText("No Video Selected")
                self.log_message.emit("No reference video selected.", "INFO")
            else:
                self.ref_status_label.setText("File Not Found")
                self.log_message.emit(f"Failed to load reference video: File Not Found at {file_path}", "ERROR")
            self.video_stack.setCurrentWidget(self.ref_status_label)

    def handle_video_error(self, error):
        self.media_player_error = True
        error_string = self.media_player.errorString()
        
        # Log a more specific, actionable error for known codec issues.
        # The code 0x80040266 is a common Windows error for "Cannot play back the file".
        if "0x80040266" in error_string or "DirectShow" in error_string:
             self.log_message.emit("Video Codec Error. Install K-Lite Codec Pack for full compatibility.", "ERROR")
        else:
             self.log_message.emit(f"Reference video player error: {error_string}", "ERROR")
        
        self.ref_status_label.setText("Media Error")
        self.video_stack.setCurrentWidget(self.ref_status_label)

    def update_timer(self):
        self.job_time = self.job_time.addSecs(1)
        self.timer_label.setText(self.job_time.toString("hh:mm:ss"))

    def update_cards(self, data):
        self.cw_card.update_values(data)
        self.tw_card.update_values(data)
        self.rot_card.update_values(data)
        self.imu_card.update_values(data)

    def on_end_print_clicked(self):
        """A graceful end to the print job."""
        self.log_message.emit("--- GRACEFUL JOB STOP ---", "INFO")
        self.main_window.send_command('M203')  # Pause Video
        self.main_window.send_command('M201')  # Projector Off
        
        self.job_timer.stop()
        if self.media_player:
            self.media_player.pause()
            
        self.end_print_button.setText("Job Stopped")
        self.end_print_button.setEnabled(False)
        self.timer_label.setStyleSheet("color: #a1a1aa;")
        self.job_ended.emit()

    def start_print_sequence(self):
        """Starts the timer, video (if available), and sensor data."""
        # Reset UI state for a new run
        self.job_time.setHMS(0,0,0)
        self.timer_label.setText("00:00:00")
        self.timer_label.setStyleSheet("") # Reset color
        self.end_print_button.setText("End Print")
        self.end_print_button.setEnabled(True)

        # Start processes
        self.job_started.emit()
        self.log_message.emit("Job sequence started. Timer and sensors are live.", "SUCCESS")
        self.job_timer.start(1000)
        
        if self.media_player and not self.media_player_error:
            self.media_player.play()
            
        if not self.sensor_worker.isRunning():
            self.sensor_worker.start()

    def stop_print_sequence(self):
        """Stops the timer, video, and sensors, typically for E-Stop."""
        if not self.job_timer.isActive(): return # Prevent double-stops

        self.job_ended.emit()
        self.log_message.emit("--- EMERGENCY STOP ---", "ERROR")
        
        # Stop all remote and local processes immediately
        self.main_window.send_command('M203') # Attempt to pause video
        self.main_window.send_command('M201') # Turn off projector
        self.main_window.ssh_worker.stop_remote_video() # Kill remote video player
        
        self.job_timer.stop()
        
        if self.media_player:
            self.media_player.pause()
        
        # This is a critical safety message, sent via main_window
        self.main_window.send_command("M112")
            
    def cleanup(self):
        # Full stop of everything on window close
        self.job_timer.stop()
        if self.media_player:
            self.media_player.stop()
            self.media_player.setMedia(QMediaContent(None))
        self.sensor_worker.stop()

if __name__ == '__main__':
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    font = QFont("Segoe UI")
    app.setFont(font)
    
    
    # Mock main window for testing
    class MockMainWindow:
        def __init__(self):
            self.job_data = {}
        def send_command(self, cmd): print(f"SENT CMD: {cmd}")

    window = QWidget()
    layout = QVBoxLayout(window)
    mock_main_window = MockMainWindow()
    display_page = DisplayPage(main_window=mock_main_window)
    layout.addWidget(display_page)
    
    window.setWindowTitle("HeliCAL Display Page")
    window.setGeometry(100, 100, 1280, 800)
    window.show()
    
    test_video_path = os.path.abspath("tube_cut.mp4") 
    if os.path.exists(test_video_path):
        display_page.set_video_source(test_video_path)
    else:
        print(f"Test video not found: {test_video_path}")

    # To test the new logic, we must now manually start the sequence
    # display_page.start_print_sequence()

    sys.exit(app.exec_())
