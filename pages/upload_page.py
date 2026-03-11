import sys
import os
from PyQt5.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QFrame,
    QSizePolicy,
    QFileDialog,
    QMessageBox,
)
from PyQt5.QtCore import Qt, pyqtSignal, QUrl
from PyQt5.QtGui import QFont, QPixmap, QPainter, QColor

# Asset path
ICON_PATH = os.path.join(os.path.dirname(__file__), "..", "assets", "icons", "upload.svg")

class DragDropZone(QFrame):
    """A widget that supports drag-and-drop and click-to-browse for files."""
    filesSelected = pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setObjectName("DragZone")
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setAlignment(Qt.AlignCenter)
        
        # Icon
        self.icon_label = QLabel()
        self.icon_label.setAlignment(Qt.AlignCenter)
        pixmap = QPixmap(ICON_PATH)
        self.icon_label.setPixmap(pixmap.scaled(64, 64, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        
        # Main Text
        self.main_text = QLabel("Drag & Drop Files Here")
        self.main_text.setObjectName("DragZoneMainText")
        self.main_text.setAlignment(Qt.AlignCenter)
        
        # Subtext
        self.sub_text = QLabel("or click to browse")
        self.sub_text.setObjectName("DragZoneSubText")
        self.sub_text.setAlignment(Qt.AlignCenter)
        
        layout.addWidget(self.icon_label)
        layout.addSpacing(10)
        layout.addWidget(self.main_text)
        layout.addWidget(self.sub_text)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            paths, _ = QFileDialog.getOpenFileNames(self, "Select Files", "", "Video/G-Code (*.mp4 *.gcode *.txt);;All Files (*)")
            if paths:
                self.filesSelected.emit(paths)
        super().mousePressEvent(event)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.setObjectName("DragZoneHover")
            self._repolish()
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        self.setObjectName("DragZone")
        self._repolish()
        event.accept()

    def dropEvent(self, event):
        self.setObjectName("DragZone")
        self._repolish()
        urls = event.mimeData().urls()
        paths = [url.toLocalFile() for url in urls]
        self.filesSelected.emit(paths)
        event.acceptProposedAction()
        
    def _repolish(self):
        self.style().unpolish(self)
        self.style().polish(self)

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
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(40, 40, 40, 40)
        main_layout.setAlignment(Qt.AlignCenter)

        header_label = QLabel("Upload Job Files")
        header_label.setObjectName("PageTitle")
        header_label.setAlignment(Qt.AlignCenter)
        
        self.drag_zone = DragDropZone()
        self.drag_zone.filesSelected.connect(self._handle_files)
        
        # File status display
        self.video_status_label = self._create_status_label("Video File (.mp4)")
        self.gcode_status_label = self._create_status_label("G-Code File (.gcode, .txt)")

        status_layout = QVBoxLayout()
        status_layout.addWidget(self.video_status_label)
        status_layout.addSpacing(10)
        status_layout.addWidget(self.gcode_status_label)
        
        self.btn_confirm = QPushButton("Confirm and Proceed")
        self.btn_confirm.setObjectName("PrimaryBtn")
        self.btn_confirm.setMinimumHeight(50)
        self.btn_confirm.clicked.connect(self._confirm_files)
        
        main_layout.addWidget(header_label)
        main_layout.addSpacing(20)
        main_layout.addWidget(self.drag_zone, 1) # Give it stretch factor
        main_layout.addSpacing(30)
        main_layout.addLayout(status_layout)
        main_layout.addSpacing(30)
        main_layout.addWidget(self.btn_confirm, 0, Qt.AlignCenter)
        self.setLayout(main_layout)

    def _create_status_label(self, title):
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        title_label = QLabel(title)
        title_label.setObjectName("StatusTitle")
        path_label = QLabel("No file selected.")
        path_label.setObjectName("StatusPath")
        path_label.setAlignment(Qt.AlignRight)
        
        layout.addWidget(title_label)
        layout.addWidget(path_label)
        widget.setProperty("path_label", path_label) # To easily access it later
        return widget

    def _handle_files(self, paths):
        for path in paths:
            if path.lower().endswith('.mp4'):
                self.video_path = path
                self.log_message.emit(f"Video file selected: {os.path.basename(path)}", "INFO")
                self.video_status_label.findChild(QLabel, "StatusPath").setText(f"<b>{os.path.basename(path)}</b>")
                self.video_status_label.findChild(QLabel, "StatusPath").setStyleSheet("color: #22c55e;") # Green for success
            elif path.lower().endswith(('.gcode', '.txt')):
                self.gcode_path = path
                self.log_message.emit(f"G-Code file selected: {os.path.basename(path)}", "INFO")
                self.gcode_status_label.findChild(QLabel, "StatusPath").setText(f"<b>{os.path.basename(path)}</b>")
                self.gcode_status_label.findChild(QLabel, "StatusPath").setStyleSheet("color: #22c55e;") # Green for success
            else:
                self.log_message.emit(f"Ignored unsupported file type: {path}", "WARNING")

    def _confirm_files(self):
        if not self.video_path or not self.gcode_path:
            QMessageBox.warning(self, "Missing Files", "Please select both a video and a G-code file.")
            return

        self.main_window.job_data['video_path'] = self.video_path
        self.main_window.job_data['gcode_path'] = self.gcode_path
        self.main_window.start_upload(self.video_path)
        self.fileConfirmed.emit()

    def _apply_styles(self):
        self.setStyleSheet("""
            #UploadPage { background-color: #09090b; }
            #PageTitle { font-size: 24pt; font-weight: bold; color: #e4e4e7; margin-bottom: 20px; }
            
            #DragZone {
                border: 2px dashed #3f3f46;
                border-radius: 20px;
                background-color: #18181b;
                min-height: 250px;
            }
            #DragZone:hover, #DragZoneHover {
                border-color: #3b82f6;
                background-color: #27272a;
            }
            #DragZoneMainText { font-size: 18pt; font-weight: bold; color: #e4e4e7; }
            #DragZoneSubText { font-size: 12pt; color: #a1a1aa; }
            
            #StatusTitle { font-size: 13pt; color: #a1a1aa; font-weight: bold; }
            #StatusPath { font-size: 13pt; color: #71717a; }
            
            #PrimaryBtn {
                background-color: #3b82f6;
                color: white;
                font-size: 14pt;
                font-weight: bold;
                padding: 12px 24px;
                border-radius: 8px;
                border: none;
            }
            #PrimaryBtn:hover { background-color: #2563eb; }
        """)

if __name__ == '__main__':
    app = QApplication(sys.argv)
    
    # Mock main window for testing
    class MockMainWindow:
        def __init__(self):
            self.job_data = {}
        def start_upload(self, path): print(f"Started upload for {path}")
        def log(self, msg, level): print(f"[{level}] {msg}")

    window = UploadPage(main_window=MockMainWindow())
    window.setWindowTitle("Upload Page Test")
    window.setGeometry(100, 100, 800, 700)
    window.show()
    sys.exit(app.exec_())

