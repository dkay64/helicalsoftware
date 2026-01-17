
import sys
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
QLabel#SummaryLabel { font-size: 12pt; color: #e4e4e7; }
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

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("RunPage")
        self.setStyleSheet(CARD_STYLE)
        
        self.is_recording = False
        self.is_rotation_active = False
        
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(20)
        main_layout.setAlignment(Qt.AlignTop)

        self.rotation_card = self._create_rotation_card()
        self.camera_card = self._create_camera_card()
        self.summary_card = self._create_summary_card()
        
        main_layout.addWidget(self.rotation_card)
        main_layout.addWidget(self.camera_card)
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

        self._set_step_enabled(self.camera_card, False)
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

    def _create_camera_card(self):
        card = self._create_card_frame()
        layout = QVBoxLayout(card)
        layout.setSpacing(15)
        header = self._create_header_label("2. CAMERA FEED")
        layout.addWidget(header)
        self.camera_placeholder = QLabel()
        self.camera_placeholder.setObjectName("CameraPlaceholder")
        self.camera_placeholder.setMinimumHeight(200)
        self.camera_placeholder.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(self.camera_placeholder)
        controls_layout = QHBoxLayout()
        controls_layout.setSpacing(15)
        start_recording_btn = QPushButton("START RECORDING")
        start_recording_btn.setObjectName("SuccessButton")
        start_recording_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        start_recording_btn.clicked.connect(self._on_start_recording)
        continue_no_rec_btn = QPushButton("Continue without recording")
        continue_no_rec_btn.setObjectName("TransparentButton")
        continue_no_rec_btn.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        continue_no_rec_btn.clicked.connect(self._on_continue_without_recording)
        controls_layout.addWidget(start_recording_btn)
        controls_layout.addWidget(continue_no_rec_btn)
        layout.addLayout(controls_layout)
        return card

    def _create_summary_card(self):
        card = self._create_card_frame()
        layout = QVBoxLayout(card)
        layout.setSpacing(15)
        header = self._create_header_label("3. PRINT SUMMARY")
        layout.addWidget(header)
        data_layout = QVBoxLayout()
        data_layout.setSpacing(8)
        self.rpm_label = QLabel("RPM: <span style='color:white;'>N/A</span>")
        self.rpm_label.setObjectName("SummaryLabel")
        self.laser_label = QLabel("Laser Power: <span style='color:white;'>N/A</span>")
        self.laser_label.setObjectName("SummaryLabel")
        time_label = QLabel("Est. Time: <span style='color:white;'>01:00:00</span>")
        time_label.setObjectName("SummaryLabel")
        data_layout.addWidget(self.rpm_label)
        data_layout.addWidget(self.laser_label)
        data_layout.addWidget(time_label)
        layout.addLayout(data_layout)
        layout.addSpacing(20)
        self.recording_status_label = QLabel("Camera not recording")
        self.recording_status_label.setObjectName("StatusLabelNotRec")
        layout.addWidget(self.recording_status_label)
        layout.addStretch()
        footer_layout = QHBoxLayout()
        footer_layout.addStretch()
        start_run_btn = QPushButton("STEP 4: START RUN")
        start_run_btn.setObjectName("PrimaryButton")
        start_run_btn.clicked.connect(self._on_start_run_clicked)
        footer_layout.addWidget(start_run_btn)
        layout.addLayout(footer_layout)
        return card

    def update_summary(self, rpm, power):
        self.rpm_label.setText(f"RPM: <span style='color:white;'>{rpm}</span>")
        self.laser_label.setText(f"Laser Power: <span style='color:white;'>{power}</span>")
        self.log_message.emit(f"Run parameters loaded - RPM: {rpm}, Laser Power: {power}", "INFO")
        
    def _on_start_rotation(self):
        self.log_message.emit("Motor Started (G33)", "INFO")
        self.is_rotation_active = True
        self.start_rotation_btn.setText("ROTATION ACTIVE")
        self.start_rotation_btn.setObjectName("ActiveStateButton")
        self.start_rotation_btn.setEnabled(False)
        self.start_rotation_btn.style().polish(self.start_rotation_btn)
        self.stop_rotation_btn.setVisible(True)
        self._set_step_enabled(self.camera_card, True)

    def _on_stop_rotation(self):
        self.log_message.emit("M5 - Spindle Off", "GCODE")
        self._reset_to_initial_state()

    def _on_start_recording(self):
        self.log_message.emit("Camera recording started.", "INFO")
        self.is_recording = True
        self._update_recording_status()
        self._set_step_enabled(self.summary_card, True)

    def _on_continue_without_recording(self):
        self.log_message.emit("Continuing without camera recording.", "INFO")
        self.is_recording = False
        self._update_recording_status()
        self._set_step_enabled(self.summary_card, True)

    def _on_start_run_clicked(self):
        """Handles the final 'Start Run' click, including a safety check."""
        if not self.is_rotation_active:
            self.log_message.emit("Safety Halt: Rotation not active. Print aborted.", "ERROR")
            return

        self.log_message.emit("G-CODE execution started.", "GCODE")
        self.runJobStarted.emit()
        
    def _update_recording_status(self):
        if self.is_recording:
            self.recording_status_label.setText("● CAMERA IS RECORDING")
            self.recording_status_label.setObjectName("StatusLabelRec")
        else:
            self.recording_status_label.setText("Camera not recording")
            self.recording_status_label.setObjectName("StatusLabelNotRec")
        
        self.recording_status_label.style().unpolish(self.recording_status_label)
        self.recording_status_label.style().polish(self.recording_status_label)

# Example usage for testing
if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = QWidget()
    window.setWindowTitle("Run Page Test")
    window.setGeometry(100, 100, 800, 900)
    window.setStyleSheet("background-color: #09090b;")
    run_page = RunPage()
    layout = QVBoxLayout(window)
    layout.addWidget(run_page)
    window.setLayout(layout)
    def on_run_started():
        print("Signal 'runJobStarted' was emitted!")
    run_page.runJobStarted.connect(on_run_started)
    window.show()
    sys.exit(app.exec_())
