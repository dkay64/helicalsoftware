import sys
import os
from PyQt5.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLineEdit,
    QLabel,
    QGroupBox,
    QSizePolicy,
    QFileDialog,
    QMessageBox,
)
from PyQt5.QtCore import Qt, pyqtSignal

class UploadPage(QWidget):
    log_message = pyqtSignal(str, str)
    fileConfirmed = pyqtSignal()

    def __init__(self, main_window=None, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self.video_path = None
        self.gcode_path = None
        self.setObjectName("UploadPage")
        self._setup_ui()
        self._apply_styles()

    def _setup_ui(self):
        """Initializes the widgets and layouts."""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(20)
        main_layout.setAlignment(Qt.AlignCenter)

        header_label = QLabel("Job File Selection")
        header_label.setObjectName("PageTitle")
        header_label.setAlignment(Qt.AlignCenter)

        # Step 1: Video Upload
        step1_group = QGroupBox("Step 1: Select Projector Video (.mp4)")
        step1_group.setMaximumWidth(900)
        step1_layout = QVBoxLayout(step1_group)
        step1_layout.setSpacing(15)

        video_input_layout = QHBoxLayout()
        self.video_path_line_edit = QLineEdit()
        self.video_path_line_edit.setPlaceholderText("No video file selected...")
        self.video_path_line_edit.setReadOnly(True)
        self.video_path_line_edit.setMinimumWidth(350)
        self.browse_video_button = QPushButton("Browse Video")
        video_input_layout.addWidget(self.video_path_line_edit)
        video_input_layout.addWidget(self.browse_video_button)
        step1_layout.addLayout(video_input_layout)

        # Step 2: G-Code Upload
        step2_group = QGroupBox("Step 2: Select G-Code File (.gcode, .txt)")
        step2_group.setMaximumWidth(900)
        step2_layout = QVBoxLayout(step2_group)
        step2_layout.setSpacing(15)

        gcode_input_layout = QHBoxLayout()
        self.gcode_path_line_edit = QLineEdit()
        self.gcode_path_line_edit.setPlaceholderText("No G-Code file selected...")
        self.gcode_path_line_edit.setReadOnly(True)
        self.gcode_path_line_edit.setMinimumWidth(350)
        self.browse_gcode_button = QPushButton("Browse G-Code")
        gcode_input_layout.addWidget(self.gcode_path_line_edit)
        gcode_input_layout.addWidget(self.browse_gcode_button)
        step2_layout.addLayout(gcode_input_layout)
        
        # Confirmation Button
        self.btn_confirm = QPushButton("Confirm Files and Proceed to Setup")
        self.btn_confirm.setObjectName("PrimaryBtn")
        self.btn_confirm.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        
        # Assemble the main layout
        main_layout.addWidget(header_label)
        main_layout.addWidget(step1_group)
        main_layout.addWidget(step2_group)
        main_layout.addWidget(self.btn_confirm, 0, Qt.AlignCenter)
        main_layout.addStretch() 

        # The container is no longer needed as we align the whole layout
        self.setLayout(main_layout)

        # --- Connect Signals ---
        self.browse_video_button.clicked.connect(self._browse_video_file)
        self.browse_gcode_button.clicked.connect(self._browse_gcode_file)
        self.btn_confirm.clicked.connect(self._confirm_files)

    def _browse_video_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choose Video File", "", "MP4 Files (*.mp4);;All Files (*)")
        if path:
            self.video_path = path
            self.video_path_line_edit.setText(path)
            self.log_message.emit(f"Selected video file: {path}", "INFO")

    def _browse_gcode_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choose G-Code File", "", "G-Code Files (*.gcode *.txt);;All Files (*)")
        if path:
            self.gcode_path = path
            self.gcode_path_line_edit.setText(path)
            self.log_message.emit(f"Selected G-Code file: {path}", "INFO")

    def _confirm_files(self):
        if not self.video_path or not self.gcode_path:
            QMessageBox.warning(self, "Missing Files", "Please select both a video file and a G-code file.")
            self.log_message.emit("File confirmation failed: one or both files are missing.", "WARNING")
            return

        if not os.path.exists(self.video_path) or not os.path.exists(self.gcode_path):
            QMessageBox.critical(self, "File Not Found", "One of the selected files could not be found.")
            return
            
        if self.main_window:
            self.log_message.emit("Video and G-code files confirmed.", "SUCCESS")
            self.main_window.job_data['video_path'] = self.video_path
            self.main_window.job_data['gcode_path'] = self.gcode_path
            self.main_window.start_upload(self.video_path)
            self.fileConfirmed.emit()

    def _apply_styles(self):
        self.setStyleSheet("""
            #UploadPage {
                background-color: #09090b;
            }
            #PageTitle {
                font-size: 24pt;
                font-weight: bold;
                color: #e4e4e7;
                margin-bottom: 10px;
            }
            QGroupBox {
                background-color: #18181b;
                border: 1px solid #27272a;
                border-radius: 12px;
                font-weight: bold;
                font-size: 16pt; 
                margin-top: 15px; 
                padding: 25px 20px 20px 20px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 0 10px;
                left: 15px;
                color: #e4e4e7;
            }
            QLineEdit {
                background-color: #27272a;
                border: 1px solid #3f3f46;
                border-radius: 8px;
                color: #e4e4e7;
                padding: 10px;
                font-size: 12pt;
            }
            QPushButton {
                background-color: #27272a;
                border: 1px solid #52525b;
                border-radius: 8px;
                color: #e4e4e7;
                padding: 10px 20px;
                font-size: 12pt;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #3f3f46;
            }
            QPushButton#PrimaryBtn {
                background-color: #3b82f6;
                border: none;
                color: white;
                font-size: 14pt;
                font-weight: bold;
                padding: 12px 24px;
                border-radius: 8px;
                margin-top: 20px;
            }
            QPushButton#PrimaryBtn:hover {
                background-color: #2563eb;
            }
        """)

