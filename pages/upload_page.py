import os
# This environment variable must be set before importing PyQt5
os.environ['QT_MULTIMEDIA_PREFERRED_PLUGINS'] = 'windowsmediafoundation'

from PyQt5.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QFrame,
    QLabel,
    QSizePolicy,
    QFileDialog,
    QStackedWidget,
    QPushButton,
    QHBoxLayout,
    QToolButton,
)
from PyQt5.QtCore import Qt, pyqtSignal, QUrl, QSize
from PyQt5.QtGui import QPixmap, QIcon
from PyQt5.QtMultimedia import QMediaPlayer, QMediaContent
from PyQt5.QtMultimediaWidgets import QVideoWidget


class DragDropZone(QFrame):
    """
    A custom QFrame that accepts drag-and-drop for video files
    and can be clicked to open a file dialog.
    """
    fileDropped = pyqtSignal(str)
    fileInvalid = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setObjectName("DragDropZone")
        self.setStyleSheet(
            """
            #DragDropZone {
                border: 3px dashed #3f3f46;
                border-radius: 20px;
                background-color: #18181b;
            }
            #DragDropZone:hover {
                border-color: #3b82f6;
                background-color: #1e1e24;
            }
            """
        )
        self.setCursor(Qt.PointingHandCursor)

        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumSize(400, 300)

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(20)

        self.icon_label = QLabel(self)
        
        # CRITICAL: Use QIcon to render SVG at high resolution for sharpness
        icon = QIcon("assets/icons/upload.svg")
        pixmap = icon.pixmap(QSize(256, 256)) # Render high-res pixmap
        
        self.icon_label.setPixmap(
            pixmap.scaled(
                128, 128, Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
        )
        self.icon_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.icon_label)

        self.main_text = QLabel("Drag & Drop Video File", self)
        self.main_text.setAlignment(Qt.AlignCenter)
        self.main_text.setStyleSheet(
            "font-size: 24px; font-weight: bold; color: #ccc; background: transparent;"
        )
        layout.addWidget(self.main_text)

        self.sub_text = QLabel("or click to browse local files", self)
        self.sub_text.setAlignment(Qt.AlignCenter)
        self.sub_text.setStyleSheet("font-size: 16px; color: #888; background: transparent;")
        layout.addWidget(self.sub_text)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if url.isLocalFile() and url.toLocalFile().lower().endswith(".mp4"):
                    event.acceptProposedAction()
                    self.setProperty("hover", True)
                    self.style().unpolish(self)
                    self.style().polish(self)
                    return
        event.ignore()

    def dragLeaveEvent(self, event):
        self.setProperty("hover", False)
        self.style().unpolish(self)
        self.style().polish(self)

    def dropEvent(self, event):
        self.setProperty("hover", False)
        self.style().unpolish(self)
        self.style().polish(self)
        for url in event.mimeData().urls():
            if url.isLocalFile():
                file_path = url.toLocalFile()
                if file_path.lower().endswith(".mp4"):
                    self.fileDropped.emit(file_path)
                    event.accept()
                    return
                else:
                    self.fileInvalid.emit("Invalid file type. Only .mp4 videos are accepted.")
                    event.ignore()
                    return
        event.ignore()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            file_path, _ = QFileDialog.getOpenFileName(
                self, "Select a Video File", "", "Video Files (*.mp4)"
            )
            if file_path:
                self.fileDropped.emit(file_path)


class UploadPage(QWidget):
    """
    Manages the two states of the upload process: Drop Zone and Preview.
    """
    fileConfirmed = pyqtSignal(str)
    log_message = pyqtSignal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("UploadPage")
        
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setAlignment(Qt.AlignCenter)
        self.stack = QStackedWidget(self)
        self.main_layout.addWidget(self.stack)

        self.file_path = None

        # State A: Drop Zone
        self.drop_zone_widget = QWidget()
        drop_zone_layout = QHBoxLayout(self.drop_zone_widget)
        drop_zone_layout.setAlignment(Qt.AlignCenter)
        self.drop_zone = DragDropZone()
        self.drop_zone.fileDropped.connect(self.on_file_loaded)
        self.drop_zone.fileInvalid.connect(self.on_file_invalid)
        drop_zone_layout.addWidget(self.drop_zone)
        self.stack.addWidget(self.drop_zone_widget)

        # State B: Video Preview
        self.video_preview_widget = self._create_preview_widget()
        self.stack.addWidget(self.video_preview_widget)

    def on_file_invalid(self, error_message):
        self.log_message.emit(error_message, "ERROR")

    def _create_preview_widget(self):
        """Creates the State B widget for video preview and confirmation."""
        preview_widget = QWidget()
        preview_layout = QVBoxLayout(preview_widget)
        preview_layout.setContentsMargins(10, 10, 10, 10)
        preview_layout.setSpacing(15)

        # --- Top: Filename Label ---
        self.filename_label = QLabel("Loaded: ...")
        self.filename_label.setAlignment(Qt.AlignCenter)
        self.filename_label.setStyleSheet("color: #888; font-size: 14px;")
        preview_layout.addWidget(self.filename_label)

        # --- Video Area ---
        self.video_widget = QVideoWidget()
        self.player = QMediaPlayer()
        self.player.setVideoOutput(self.video_widget)
        self.video_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        preview_layout.addWidget(self.video_widget, 1)

        # --- Playback Controls ---
        controls_layout = QHBoxLayout()
        controls_layout.setAlignment(Qt.AlignCenter)
        self.play_pause_button = QToolButton()
        self.play_pause_button.setIconSize(QSize(48, 48))
        self.play_pause_button.setStyleSheet("QToolButton { border: none; }")
        self.play_pause_button.clicked.connect(self.toggle_playback)
        controls_layout.addWidget(self.play_pause_button)
        preview_layout.addLayout(controls_layout)

        # --- Footer Bar ---
        footer_bar_layout = QHBoxLayout()
        
        # 'Change File' button (Left)
        change_file_button = QPushButton("Change File")
        change_file_button.clicked.connect(self.reset)
        change_file_button.setStyleSheet("""
            QPushButton {
                border: 1px solid #3f3f46;
                color: #e4e4e7;
                background-color: transparent;
                border-radius: 8px;
                padding: 10px 20px;
                font-weight: bold;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #27272a;
            }
        """)
        footer_bar_layout.addWidget(change_file_button)

        footer_bar_layout.addStretch() # Spacer

        # 'Next Step' button (Right)
        self.next_step_button = QPushButton("NEXT STEP: MACHINE SETUP")
        self.next_step_button.clicked.connect(self.confirm_file)
        self.next_step_button.setStyleSheet("""
            QPushButton {
                background-color: #3b82f6;
                color: white;
                border-radius: 8px;
                padding: 10px 20px;
                font-weight: bold;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #2563eb;
            }
        """)
        footer_bar_layout.addWidget(self.next_step_button)
        preview_layout.addLayout(footer_bar_layout)

        # Connect signals
        self.player.stateChanged.connect(self.on_player_state_changed)
        self.on_player_state_changed(self.player.state())

        return preview_widget

    def on_file_loaded(self, file_path):
        try:
            self.file_path = file_path
            display_name = os.path.basename(file_path)
            if len(display_name) > 40:
                display_name = "..." + display_name[-37:]
            
            self.filename_label.setText(f"Loaded: {display_name}")
            self.player.setMedia(QMediaContent(QUrl.fromLocalFile(file_path)))
            
            self.stack.setCurrentWidget(self.video_preview_widget)
            self.log_message.emit(f"File loaded: {display_name}", "INFO")
            self.player.play()

        except Exception as e:
            self.log_message.emit(f"Failed to load video: {e}. The file may be corrupt or in an unsupported format.", "ERROR")
            self.reset()

    def toggle_playback(self):
        if self.player.state() == QMediaPlayer.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def on_player_state_changed(self, state):
        if state == QMediaPlayer.PlayingState:
            self.play_pause_button.setIcon(QIcon('assets/icons/pause.svg'))
        else:
            self.play_pause_button.setIcon(QIcon('assets/icons/play.svg'))

    def confirm_file(self):
        if self.file_path:
            self.log_message.emit("File confirmed, proceeding to machine setup.", "INFO")
            self.fileConfirmed.emit(self.file_path)

    def reset(self):
        self.player.stop()
        self.file_path = None
        self.stack.setCurrentWidget(self.drop_zone_widget)