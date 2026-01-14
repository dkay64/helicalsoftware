import os
os.environ['QT_MULTIMEDIA_PREFERRED_PLUGINS'] = 'windowsmediafoundation'
import sys
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QStackedWidget, QLabel, QFrame, QTextEdit, QSplitter,
    QToolButton
)
from PyQt5.QtGui import QIcon
from PyQt5.QtCore import Qt, QSize

from pages.upload_page import UploadPage

def load_stylesheet(app):
    """Loads the global QSS stylesheet for the application."""
    style_sheet = """
    /* --- Main Window & Canvas --- */
    #MainWindow, #Canvas {
        background-color: #09090b;
    }
    QWidget {
        color: #e4e4e7; /* Default text color */
        font-family: 'Segoe UI';
    }

    /* --- Header --- */
    QFrame#Header {
        background-color: #09090b;
        border-bottom: 1px solid #27272a;
    }
    QLabel#Header_Title {
        font-size: 24px;
        font-weight: bold;
    }

    /* --- Sidebar --- */
    QFrame#Sidebar {
        background-color: #18181b;
        border-right: 1px solid #27272a;
    }
    #Sidebar QToolButton {
        background-color: transparent;
        border: 2px solid transparent; /* Reserve space for border */
        color: #e4e4e7;
        font-size: 12px;
        font-weight: bold;
        min-width: 90px;
        max-width: 90px;
        min-height: 90px;
        max-height: 90px;
        border-radius: 8px;
    }
    #Sidebar QToolButton:hover {
        background-color: #27272a;
    }
    #Sidebar QToolButton:checked {
        background-color: #27272a;
        border: 2px solid #3b82f6;
    }

    /* Distinct style for bottom buttons */
    #Sidebar QToolButton.bottom_button {
        border-top: 1px solid #27272a;
        border-radius: 0;
    }
    #Sidebar QToolButton.bottom_button:hover {
        background-color: #27272a;
    }

    /* --- Log Panel --- */
    QFrame#Log_Panel {
        background-color: #18181b;
        border-top: 1px solid #27272a;
    }
    #Log_Panel_Title {
        font-size: 14px;
        font-weight: bold;
        padding: 8px;
    }
    QTextEdit#Log_Display {
        background-color: #09090b;
        color: #22c55e;
        font-family: 'monospace';
        border: none;
    }

    /* --- Splitter Handle --- */
    QSplitter::handle:vertical {
        height: 2px;
        background-color: #27272a;
    }
    QSplitter::handle:vertical:hover {
        background-color: #3b82f6;
    }

    /* --- STOP Button --- */
    #Stop_Button {
        background-color: #ef4444;
        color: white;
        font-weight: bold;
        font-size: 16px;
        border-radius: 8px;
        padding: 10px 20px;
    }
    #Stop_Button:hover {
        background-color: #dc2626;
    }
    
    /* --- Page Title --- */
    QLabel#Page_Title {
        font-size: 28px;
        font-weight: bold;
    }
    """
    app.setStyleSheet(style_sheet)

# --- Placeholder Page Widget ---
class PlaceholderPage(QWidget):
    def __init__(self, name, parent=None):
        super().__init__(parent)
        self.setObjectName("Canvas")
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        label = QLabel(name, self)
        label.setObjectName("Page_Title")
        layout.addWidget(label)

# --- Main Application Window ---
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setObjectName("MainWindow")
        self.setWindowTitle("HeliCAL Control Station")
        self.setGeometry(100, 100, 1600, 900)

        central_widget = QWidget()
        root_layout = QVBoxLayout(central_widget)
        root_layout.setSpacing(0)
        root_layout.setContentsMargins(0, 0, 0, 0)

        header = self.create_header()
        root_layout.addWidget(header)

        body_widget = QWidget()
        body_layout = QHBoxLayout(body_widget)
        body_layout.setSpacing(0)
        body_layout.setContentsMargins(0, 0, 0, 0)
        
        sidebar = self.create_sidebar()
        body_layout.addWidget(sidebar)

        # Right content area with splitter
        splitter = QSplitter(Qt.Vertical)
        
        self.stacked_widget = QStackedWidget()
        self.upload_page = UploadPage()  # Create an instance of the upload page
        self.upload_page.fileConfirmed.connect(self.go_to_machine_setup)

        self.stacked_widget.addWidget(PlaceholderPage("HOME"))
        self.stacked_widget.addWidget(self.upload_page)  # Add the instance
        self.stacked_widget.addWidget(PlaceholderPage("MACHINE SETUP"))
        self.stacked_widget.addWidget(PlaceholderPage("RUN JOB"))
        self.stacked_widget.addWidget(PlaceholderPage("DISPLAY"))
        
        log_panel = self.create_log_panel()

        splitter.addWidget(self.stacked_widget)
        splitter.addWidget(log_panel)
        
        # Set initial sizes for the splitter
        splitter.setSizes([self.height() - 230, 150]) # Header is 80, log is 150

        body_layout.addWidget(splitter, 1)

        root_layout.addWidget(body_widget, 1)
        self.setCentralWidget(central_widget)

    def create_header(self):
        header_widget = QFrame()
        header_widget.setObjectName("Header")
        header_widget.setFixedHeight(80)
        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(30, 0, 30, 0)

        title = QLabel("HeliCAL")
        title.setObjectName("Header_Title")
        
        status_layout = QHBoxLayout()
        status_dot = QLabel()
        status_dot.setFixedSize(12, 12)
        status_dot.setStyleSheet("background-color: #22c55e; border-radius: 6px;")
        status_label = QLabel("Connected")
        status_layout.addWidget(status_dot)
        status_layout.addWidget(status_label)
        status_layout.setSpacing(10)

        stop_button = QPushButton("STOP")
        stop_button.setObjectName("Stop_Button")
        
        header_layout.addWidget(title)
        header_layout.addStretch()
        header_layout.addLayout(status_layout)
        header_layout.addSpacing(20)
        header_layout.addWidget(stop_button)
        return header_widget

    def create_sidebar(self):
        sidebar_widget = QFrame()
        sidebar_widget.setObjectName("Sidebar")
        sidebar_widget.setFixedWidth(120)
        
        sidebar_layout = QVBoxLayout(sidebar_widget)
        sidebar_layout.setContentsMargins(15, 15, 15, 15)
        sidebar_layout.setSpacing(15)
        sidebar_layout.setAlignment(Qt.AlignTop | Qt.AlignCenter)

        # Tuples of (Text, icon_name)
        button_defs = [
            ("HOME", "home"), ("UPLOAD", "upload"), ("SETUP", "machine_setup"),
            ("RUN", "play"), ("DISPLAY", "display")
        ]
        
        self.nav_buttons = []
        for i, (text, icon_name) in enumerate(button_defs):
            btn = QToolButton()
            btn.setText(text)
            btn.setIcon(QIcon(f"assets/icons/{icon_name}.svg"))
            btn.setIconSize(QSize(40, 40))
            btn.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            btn.setCheckable(True)
            btn.clicked.connect(lambda _, b=btn, idx=i: self.handle_nav_click(b, idx))
            sidebar_layout.addWidget(btn)
            self.nav_buttons.append(btn)
        
        self.nav_buttons[0].setChecked(True)

        sidebar_layout.addStretch()

        # Bottom buttons
        bottom_button_defs = [("ADVANCED", "advanced_settings"), ("JOG", "jog")]
        for text, icon_name in bottom_button_defs:
            btn = QToolButton()
            btn.setObjectName("bottom_button")
            btn.setText(text)
            btn.setIcon(QIcon(f"assets/icons/{icon_name}.svg"))
            btn.setIconSize(QSize(40,40))
            btn.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            sidebar_layout.addWidget(btn)
        
        return sidebar_widget

    def create_log_panel(self):
        log_widget = QFrame()
        log_widget.setObjectName("Log_Panel")
        log_widget.setMinimumHeight(50) # Allow it to be shrunk
        log_layout = QVBoxLayout(log_widget)
        log_layout.setContentsMargins(0, 0, 0, 0)
        log_layout.setSpacing(0)
        
        title = QLabel("OUTPUT LOG")
        title.setObjectName("Log_Panel_Title")
        title.setAlignment(Qt.AlignCenter)

        log_display = QTextEdit()
        log_display.setObjectName("Log_Display")
        log_display.setReadOnly(True)
        log_display.setText("--- System log initialized ---\n")

        log_layout.addWidget(title)
        log_layout.addWidget(log_display, 1)
        
        return log_widget

    def handle_nav_click(self, clicked_btn, page_index):
        for btn in self.nav_buttons:
            btn.setChecked(btn is clicked_btn)
        self.stacked_widget.setCurrentIndex(page_index)

    def go_to_machine_setup(self):
        """Switches to the Machine Setup page."""
        # Index 2 corresponds to the "SETUP" button
        machine_setup_button = self.nav_buttons[2] 
        machine_setup_button.click() 


if __name__ == '__main__':
    app = QApplication(sys.argv)
    load_stylesheet(app)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())