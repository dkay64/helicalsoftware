import sys
import os
from PyQt5.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QFrame,
    QSizePolicy,
    QSpacerItem,
    QGraphicsOpacityEffect,
    QMessageBox,
)
from PyQt5.QtGui import QFont, QColor
from PyQt5.QtCore import Qt, pyqtSignal, QSize

# QSS Style for the entire page and components
CARD_STYLE = """
QFrame#RunPage {
    background-color: #09090b;
}

QFrame.Card {
    background-color: #18181b;
    border: 1px solid #27272a;
    border-radius: 12px;
}

QLabel#HeaderLabel {
    font-size: 16pt;
    font-weight: bold;
    color: white;
    padding-bottom: 10px;
}

QPushButton#PrimaryButton {
    background-color: #3b82f6;
    color: white;
    font-weight: bold;
    font-size: 14pt;
    padding: 12px;
    border-radius: 8px;
    border: none;
}
QPushButton#PrimaryButton:hover {
    background-color: #2563eb;
}

QPushButton#ActiveStateButton {
    background-color: #22c55e;
    color: white;
    font-weight: bold;
    font-size: 14pt;
    padding: 12px;
    border-radius: 8px;
    border: none;
}

QPushButton#StopButton {
    background-color: transparent;
    color: #ef4444;
    font-size: 11pt;
    font-weight: bold;
    border: 1px solid #ef4444;
    border-radius: 8px;
    padding: 8px 12px;
}
QPushButton#StopButton:hover {
    background-color: #ef4444;
    color: white;
}

QPushButton#PendingButton {
    background-color: #3f3f46; /* A neutral gray */
    color: #a1a1aa;
    font-weight: bold;
    font-size: 14pt;
    padding: 12px;
    border-radius: 8px;
    border: none;
    cursor: not-allowed;
}

QPushButton#SuccessButton {
    background-color: #22c55e;
    color: white;
    font-weight: bold;
    font-size: 14pt;
    padding: 12px;
    border-radius: 8px;
    border: none;
}
QPushButton#SuccessButton:hover {
    background-color: #16a34a;
}

QPushButton#TransparentButton {
    background-color: transparent;
    color: #a1a1aa; /* zinc-400 */
    font-size: 11pt;
    border: none;
}
QPushButton#TransparentButton:hover {
    color: #e4e4e7; /* zinc-200 */
}

QLabel#CameraPlaceholder { background-color: black; border-radius: 8px; }
QTextEdit#SummaryText { 
    font-size: 11pt; 
    color: #a1a1aa;
    background-color: #09090b;
    border: 1px solid #27272a;
    border-radius: 8px;
    font-family: 'monospace';
}
QLabel#SummaryLabel { font-size: 12pt; color: #a1a1aa; }
QLabel#StatusLabelRec { color: #ef4444; font-weight: bold; font-size: 11pt; }
QLabel#StatusLabelNotRec { color: #71717a; font-size: 11pt; }

/* Custom styles for QMessageBox */
QMessageBox {
    background-color: #18181b;
}
QMessageBox QLabel {
    color: #e4e4e7;
    font-size: 12pt;
}
QMessageBox QPushButton {
    background-color: #27272a;
    color: #e4e4e7;
    border-radius: 8px;
    padding: 8px 16px;
    min-width: 80px;
    border: 1px solid #3f3f46;
}
QMessageBox QPushButton:hover {
    background-color: #3f3f46;
}
"""

class RunPage(QWidget):
    runJobStarted = pyqtSignal()
    log_message = pyqtSignal(str, str)

    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.setObjectName("RunPage")
        self.setStyleSheet(CARD_STYLE)
        self.main_window = main_window
        
        self.is_rotation_active = False
        
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(20)
        main_layout.setAlignment(Qt.AlignTop)

        self.rotation_card = self._create_rotation_card()
        self.summary_card = self._create_summary_card()
        
        main_layout.addWidget(self.rotation_card)
        main_layout.addWidget(self.summary_card)
        main_layout.addStretch()

        self._reset_to_initial_state()

    def _set_step_enabled(self, frame, enabled):
        """Applies a 'ghosting' effect to a frame to indicate its enabled state."""
        frame.setEnabled(enabled)
        opacity_effect = QGraphicsOpacityEffect(frame)
        opacity_effect.setOpacity(1.0 if enabled else 0.3)
        frame.setGraphicsEffect(opacity_effect)

    def _reset_to_initial_state(self):
        """Resets the entire page to its default state."""
        self.is_rotation_active = False

        self.start_rotation_btn.setText("START ROTATION")
        self.start_rotation_btn.setObjectName("PrimaryButton")
        self.start_rotation_btn.setEnabled(True)
        self.stop_rotation_btn.setVisible(False)
        self.start_rotation_btn.style().polish(self.start_rotation_btn) # Re-apply style

        self._set_step_enabled(self.summary_card, False)

    def _create_card_frame(self):
        card = QFrame()
        card.setObjectName("CardFrame")
        card.setProperty("class", "Card")
        card.setContentsMargins(25, 25, 25, 25)
        return card

    def _create_header_label(self, text):
        label = QLabel(text)
        label.setObjectName("HeaderLabel")
        return label
        
    def _create_rotation_card(self):
        card = self._create_card_frame()
        layout = QVBoxLayout(card)
        layout.setSpacing(15)

        header = self._create_header_label("1. START ROTATION")
        
        self.start_rotation_btn = QPushButton("START ROTATION")
        self.start_rotation_btn.setObjectName("PrimaryButton")
        self.start_rotation_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.start_rotation_btn.clicked.connect(self._on_start_rotation)
        
        self.stop_rotation_btn = QPushButton("Stop Rotation")
        self.stop_rotation_btn.setObjectName("StopButton")
        self.stop_rotation_btn.clicked.connect(self._on_stop_rotation)
        self.stop_rotation_btn.setVisible(False)

        button_layout = QHBoxLayout()
        button_layout.addWidget(self.start_rotation_btn)
        button_layout.addSpacing(15)
        button_layout.addWidget(self.stop_rotation_btn)

        layout.addWidget(header)
        layout.addLayout(button_layout)
        return card



    def _create_summary_card(self):
        card = self._create_card_frame()
        layout = QVBoxLayout(card)
        layout.setSpacing(15)
        header = self._create_header_label("3. RUN SUMMARY & START")
        layout.addWidget(header)
        
        data_layout = QVBoxLayout()
        data_layout.setSpacing(8)
        
        self.video_file_label = QLabel("Video File: <span style='color:white;'>N/A</span>")
        self.video_file_label.setObjectName("SummaryLabel")
        
        self.rpm_label = QLabel("Spindle RPM: <span style='color:white;'>N/A</span>")
        self.rpm_label.setObjectName("SummaryLabel")
        
        self.power_label = QLabel("Laser Power: <span style='color:white;'>N/A</span>")
        self.power_label.setObjectName("SummaryLabel")

        self.feed_rate_label = QLabel("Feed Rate: <span style='color:white;'>N/A</span>")
        self.feed_rate_label.setObjectName("SummaryLabel")
        
        time_label = QLabel("Est. Time: <span style='color:white;'>01:00:00</span>")
        time_label.setObjectName("SummaryLabel")
        
        data_layout.addWidget(self.video_file_label)
        data_layout.addWidget(self.rpm_label)
        data_layout.addWidget(self.power_label)
        data_layout.addWidget(self.feed_rate_label)
        data_layout.addWidget(time_label)
        
        layout.addLayout(data_layout)
        layout.addSpacing(20)
        
        layout.addStretch()
        
        footer_layout = QHBoxLayout()
        footer_layout.addStretch()
        self.start_run_btn = QPushButton("UPLOADING VIDEO...")
        self.start_run_btn.setObjectName("PendingButton")
        self.start_run_btn.clicked.connect(self._on_start_run_clicked)
        self.start_run_btn.setEnabled(False)  # Disabled by default
        footer_layout.addWidget(self.start_run_btn)
        layout.addLayout(footer_layout)
        return card

    def update_summary(self):
        """Updates the summary labels with all job parameters."""
        job_data = self.main_window.job_data
        video_path = job_data.get('video_path', 'N/A')
        feed_rate = job_data.get('feed_rate', 'N/A')
        rpm = job_data.get('rpm', 'N/A')
        power = job_data.get('power', 'N/A')
        
        self.video_file_label.setText(f"Video File: <span style='color:white;'>{os.path.basename(video_path)}</span>")
        self.rpm_label.setText(f"Spindle RPM: <span style='color:white;'>{rpm}</span>")
        self.power_label.setText(f"Laser Power: <span style='color:white;'>{power}</span>")
        self.feed_rate_label.setText(f"Feed Rate: <span style='color:white;'>{feed_rate} mm/s</span>")
        
        self.log_message.emit("Run parameters loaded into summary view.", "INFO")

    def on_upload_complete(self):
        """SLOT: Called when the video has finished uploading in the background."""
        self.log_message.emit("Video upload complete. Ready to start job.", "SUCCESS")
        self.start_run_btn.setText("START JOB")
        self.start_run_btn.setEnabled(True)
        self.start_run_btn.setObjectName("PrimaryButton")
        self.start_run_btn.style().polish(self.start_run_btn)
        
    def _on_start_rotation(self):
        """Retrieves RPM from job_data and sends the G33 command."""
        rpm = self.main_window.job_data.get('rpm', 0)
        self.log_message.emit(f"Starting rotation at {rpm} RPM.", "INFO")
        self.main_window.send_command(f"G33 A{rpm}")
        
        self.is_rotation_active = True
        self.start_rotation_btn.setText("ROTATION ACTIVE")
        self.start_rotation_btn.setObjectName("ActiveStateButton")
        self.start_rotation_btn.setEnabled(False)
        self.start_rotation_btn.style().polish(self.start_rotation_btn)
        self.stop_rotation_btn.setVisible(True)
        self._set_step_enabled(self.summary_card, True)

    def _on_stop_rotation(self):
        # M5 is spindle stop, a good command for this action
        self.main_window.send_command("G33 A0")
        self._reset_to_initial_state()



    def _on_start_run_clicked(self):
        """
        Handles the final 'Start Run' click.
        Sends setup G-codes, starts the remote video, and triggers the job.
        """
        self.log_message.emit("'_on_start_run_clicked' entered.", "INFO")

        if not self.is_rotation_active:
            self.log_message.emit("Safety Halt: Rotation not active. Print aborted.", "ERROR")
            QMessageBox.critical(self, "Safety Halt", "Rotation is not active. Please start rotation before running the job.")
            return
        
        self.log_message.emit("Rotation check passed.", "INFO")

        power = self.main_window.job_data.get('power', 0)
        feed_rate = self.main_window.job_data.get('feed_rate', 100) # Default feed rate
        video_path = self.main_window.job_data.get('video_path')

        if not video_path:
            self.log_message.emit("Critical Error: Video path not found in job data.", "ERROR")
            QMessageBox.critical(self, "Job Error", "Cannot start job: The video path is missing. Please go back to the upload step.")
            return
            
        self.log_message.emit(f"Video path found: {video_path}", "INFO")

        self.log_message.emit("--- FINAL JOB START SEQUENCE ---", "SUCCESS")
        
        # 1. Send Setup G-Codes
        self.main_window.send_command("M200") # Projector On
        self.main_window.send_command(f"F{feed_rate}")   # Set Feed Rate

        # 2. Start Remote Video Playback
        self.main_window.start_remote_video(video_path)

        # 3. Send Start Trigger (Projector)
        self.main_window.send_command('M202')
        
        # 4. Transition to Display Page (the signal will do this)
        self.log_message.emit("Emitting runJobStarted signal.", "INFO")
        self.runJobStarted.emit()
        


# Example usage for testing
if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = QWidget()
    window.setWindowTitle("Run Page Test")
    window.setGeometry(100, 100, 800, 900)
    
    # Mock main window for testing
    class MockMainWindow:
        def __init__(self):
            self.job_data = {'rpm': 1500, 'power': 200, 'feed_rate': 50, 'video_path': '/fake/path/video.mp4'}
        def send_command(self, cmd): print(f"SENT CMD: {cmd}")
        def start_remote_video(self): print("STARTING REMOTE VIDEO")

    window.setStyleSheet("background-color: #09090b;")
    run_page = RunPage(main_window=MockMainWindow())
    layout = QVBoxLayout(window)
    layout.addWidget(run_page)
    window.setLayout(layout)
    
    def on_run_started():
        print("Signal 'runJobStarted' was emitted!")
        
    run_page.runJobStarted.connect(on_run_started)
    run_page.update_summary() # Manually call for test
    
    window.show()
    sys.exit(app.exec_())
