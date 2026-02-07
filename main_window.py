import os
import sys
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QStackedWidget, QLabel, QFrame, QTextEdit, QSplitter,
    QToolButton, QMessageBox, QInputDialog, QLineEdit, QFileDialog
)
from PyQt5.QtGui import QIcon
from PyQt5.QtCore import Qt, QSize, QDateTime, pyqtSignal

from backend.ssh_worker import SSHWorker
from pages.upload_page import UploadPage
from pages.setup_page import SetupPage
from pages.run_page import RunPage
from pages.display_page import DisplayPage
from components.jog_dialog import JogDialog

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
    /* --- Display Page --- */
    #Card {
        background-color: #1a1a1c;
        border-radius: 10px;
        padding: 15px;
        border: 1px solid #27272a;
    }
    #Card QLabel {
        color: #e4e4e7;
        font-size: 12px;
    }
    #Card QLabel[cssClass="card-title"] {
        font-size: 16px;
        font-weight: bold;
        padding-bottom: 10px;
    }
    #Card QLabel[cssClass="sensor-label"] {
        font-weight: bold;
    }
    #Card QLabel[cssClass="target-value"] {
        color: #a1a1aa;
    }
    #Card QLabel[cssClass="actual-value"] {
        color: #22c55e; /* Green */
        font-weight: bold;
    }
    
    /* --- Global Dialogs (Pop-ups) --- */
    QDialog, QMessageBox, QInputDialog {
        background-color: #18181b;
        color: #e4e4e7;
    }
    /* Labels inside Dialogs */
    QDialog QLabel, QMessageBox QLabel, QInputDialog QLabel {
        color: #e4e4e7;
        background-color: transparent;
    }
    /* Buttons inside Dialogs */
    QDialog QPushButton, QMessageBox QPushButton, QInputDialog QPushButton {
        background-color: #3f3f46;
        border: 1px solid #52525b;
        border-radius: 6px;
        color: white;
        padding: 6px 16px;
        min-width: 70px;
    }
    QDialog QPushButton:hover, QMessageBox QPushButton:hover, QInputDialog QPushButton:hover {
        background-color: #52525b;
    }
    QDialog QPushButton:pressed {
        background-color: #27272a;
    }
    /* Input Fields (e.g. Password Prompt) */
    QInputDialog QLineEdit {
        background-color: #27272a;
        border: 1px solid #3f3f46;
        border-radius: 4px;
        color: white;
        padding: 6px;
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
    upload_complete = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setObjectName("MainWindow")
        self.setWindowTitle("HeliCAL Control Station")
        self.setGeometry(100, 100, 1600, 900)

        self.job_data = {}
        self.is_connected = False
        self.connection_attempt_active = False

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
        
        # --- Page Creation ---
        # Pass `self` (the main window) to each page so they can communicate back
        self.stacked_widget = QStackedWidget()
        self.upload_page = UploadPage(main_window=self)
        self.setup_page = SetupPage(main_window=self)
        self.run_page = RunPage(main_window=self)
        self.display_page = DisplayPage(main_window=self)
        
        # --- Page Connections ---
        self.upload_page.fileConfirmed.connect(self.go_to_machine_setup)
        self.setup_page.setupCompleted.connect(self.go_to_run_job)
        self.run_page.runJobStarted.connect(self.go_to_display_page)
        self.upload_complete.connect(self.run_page.on_upload_complete)

        self.stacked_widget.addWidget(PlaceholderPage("HOME"))
        self.stacked_widget.addWidget(self.upload_page)
        self.stacked_widget.addWidget(self.setup_page)
        self.stacked_widget.addWidget(self.run_page)
        self.stacked_widget.addWidget(self.display_page)

        # Connect log signals
        self.upload_page.log_message.connect(self.append_log)
        self.setup_page.log_message.connect(self.append_log)
        self.run_page.log_message.connect(self.append_log)
        self.display_page.log_message.connect(self.append_log)
        
        log_panel = self.create_log_panel()

        splitter.addWidget(self.stacked_widget)
        splitter.addWidget(log_panel)
        
        # Set initial sizes for the splitter
        splitter.setSizes([self.height() - 230, 150]) # Header is 80, log is 150

        body_layout.addWidget(splitter, 1)

        root_layout.addWidget(body_widget, 1)
        self.setCentralWidget(central_widget)
        
        # Connect the global emergency stop button to the trigger
        self.emergency_stop_button.clicked.connect(self.trigger_emergency_stop)

        # --- Backend Integration ---
        self.ssh_worker = SSHWorker()
        self.ssh_worker.log_message.connect(self.append_log)
        self.ssh_worker.connection_status.connect(self.handle_connection_status)
        self.ssh_worker.file_uploaded.connect(self._on_file_uploaded)

        # Initialize Jog Dialog - it can now send commands through the main window
        self.jog_dialog = JogDialog(command_callback=self.send_command, parent=self)
        self.sidebar.jogBtn.clicked.connect(self.open_jog_dialog)

        # --- Job State Tracking ---
        self.is_job_running = False
        self.display_page.job_started.connect(self.handle_job_start)
        self.display_page.job_ended.connect(self.handle_job_end)

        # --- Data Connections ---
        # Route sensor data from the display page's worker to other components
        self.display_page.sensor_worker.data_updated.connect(self.route_sensor_data)
        
        # Start the sensor worker immediately to get live data
        self.display_page.sensor_worker.start()

        # Attempt to auto-connect on startup
        self.attempt_auto_connect()

    def _on_file_uploaded(self, remote_path):
        """SLOT: Stores the remote path of the uploaded file for later use."""
        self.append_log(f"File upload complete. Remote path: {remote_path}", "SUCCESS")
        self.job_data['remote_video_path'] = remote_path
        self.upload_complete.emit()

    def attempt_auto_connect(self):
        """Prompts for password and starts the SSH worker thread."""
        if self.ssh_worker.isRunning():
            self.append_log("SSH worker is already running.", "INFO")
            return

        password, ok = QInputDialog.getText(self, "SSH Connection", "Enter password for 'jetson':", QLineEdit.Password)

        if ok:
            self.append_log("Attempting to connect...", "INFO")
            self.connection_attempt_active = True
            self.ssh_worker.password = password if password else ""
            self.ssh_worker.start()
        else:
            self.append_log("Connection cancelled by user.", "INFO")

    def start_upload(self, local_path):
        """
        Starts uploading a file to a predefined location on the remote machine.
        """
        if not self.is_connected:
            self.append_log("Cannot start upload, not connected.", "ERROR")
            return

        filename = os.path.basename(local_path)
        # Use a consistent remote directory for job files
        remote_path = f"{self.ssh_worker.remote_dir}/current_job_video.mp4"
        
        self.append_log(f"Starting background upload: {filename} -> {remote_path}", "INFO")
        self.ssh_worker.upload_file(local_path, remote_path)

    def start_remote_video(self, path):
        """API for pages. Triggers playback of a video at a given remote path."""
        if not self.is_connected:
            self.append_log("Cannot start remote video, not connected.", "ERROR")
            return

        if not path:
            self.append_log("Cannot start remote video, no remote path provided.", "ERROR")
            return

        self.append_log(f"Requesting remote video playback for: {path}", "INFO")
        self.ssh_worker.play_remote_video(path)

    def upload_video_for_playback(self):
        """Opens a dialog to upload a video for immediate remote playback."""
        if not self.is_connected:
            self.append_log("Connect to the remote machine before uploading.", "WARNING")
            return
            
        local_path, _ = QFileDialog.getOpenFileName(self, "Choose Video to Upload", "", "MP4 files (*.mp4)")
        if not local_path:
            return

        filename = os.path.basename(local_path)
        # This is for immediate playback, so we can use a generic name
        remote_path = f"{self.ssh_worker.remote_dir}/{filename}"
        
        self.append_log(f"Starting direct upload: {local_path} -> {remote_path}", "INFO")
        
        def play_after_upload(r_path):
            self.start_remote_video(r_path)
            # Disconnect to avoid it firing on subsequent uploads
            try:
                self.ssh_worker.file_uploaded.disconnect(play_after_upload)
            except TypeError:
                pass # Already disconnected

        self.ssh_worker.file_uploaded.connect(play_after_upload)
        self.ssh_worker.upload_file(local_path, remote_path)

    def handle_connection_status(self, connected):
        """Updates the connection status indicator in the header."""
        self.is_connected = connected
        if connected:
            self.connection_attempt_active = False
            self.status_dot.setStyleSheet("background-color: #22c55e; border-radius: 6px;") # Green
            self.status_label.setText("Connected")
            self.conn_btn.setText("DISCONNECT")
            self.append_log("Connected", "SUCCESS")
        else:
            self.status_dot.setStyleSheet("background-color: #ef4444; border-radius: 6px;") # Red
            self.status_label.setText("Disconnected")
            self.conn_btn.setText("CONNECT")
            if self.connection_attempt_active:
                QMessageBox.warning(self, "Connection Failed", 
                                    "Could not connect to Jetson. Check cables and try again.")
                self.connection_attempt_active = False

    def toggle_connection(self):
        """Handles the logic for the Connect/Disconnect button."""
        if self.is_connected:
            reply = QMessageBox.question(self, 'Confirm Disconnect', 
                                       "Are you sure you want to disconnect from the Jetson?",
                                       QMessageBox.Yes | QMessageBox.No,
                                       QMessageBox.No)
            if reply == QMessageBox.Yes:
                self.append_log("Disconnecting...", "INFO")
                self.ssh_worker.stop()
                # Manually update status as stop() might not emit a signal
                self.handle_connection_status(False)
        else:
            self.attempt_auto_connect()
            
    def send_command(self, gcode):
        """Global helper to send a G-code command via the SSH worker."""
        if self.is_connected:
            self.ssh_worker.send_gcode(gcode)
        else:
            self.append_log(f"Blocked command, not connected: {gcode}", "WARNING")

    def append_log(self, message, level="INFO"):
        """Appends a formatted message to the output log."""
        color_map = {
            "INFO": "#a1a1aa", # Gray
            "SUCCESS": "#22c55e", # Green
            "ERROR": "#ef4444", # Red
            "GCODE": "#3b82f6", # Blue
            "REMOTE": "#06b6d4", # Cyan
            "WARNING": "#f97316" # Orange
        }
        color = color_map.get(level, "#e4e4e7") # Default to light gray
        
        timestamp = QDateTime.currentDateTime().toString("hh:mm:ss")
        formatted_message = f'<span style="color: #6b7280;">{timestamp} | </span><span style="color: {color};">{message}</span>'
        
        self.output_log.append(formatted_message)
        self.output_log.verticalScrollBar().setValue(self.output_log.verticalScrollBar().maximum())


    def route_sensor_data(self, data):
        """Routes sensor data to other components that need it."""
        # Extract counterweight coordinates for the Jog DRO
        r = data.get("cw_r", 0.0)
        t = data.get("cw_t", 0.0)
        z = data.get("cw_z", 0.0)
        self.jog_dialog.update_dro(r, t, z)

    def handle_job_start(self):
        """SLOT: Sets the job running flag to True."""
        self.is_job_running = True
        self.append_log("Job started. Safety lock engaged for Jog control.", "INFO")

    def handle_job_end(self):
        """SLOT: Sets the job running flag to False."""
        self.is_job_running = False
        self.append_log("Job ended. Jog control safety lock disengaged.", "INFO")

    def open_jog_dialog(self):
        """Safety-checked method to open the Jog Dialog."""
        if self.is_job_running:
            self.append_log("Safety Lock: Blocked attempt to open Jog Dialog while job is running.", "WARNING")
            QMessageBox.warning(self, "Safety Lock", "Cannot open Jog Dialog while a print job is active.")
            return
        self.jog_dialog.exec_()

    def create_header(self):
        header_widget = QFrame()
        header_widget.setObjectName("Header")
        header_widget.setFixedHeight(80)
        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(30, 0, 30, 0)

        title = QLabel("HeliCAL")
        title.setObjectName("Header_Title")
        
        status_layout = QHBoxLayout()
        self.status_dot = QLabel()
        self.status_dot.setFixedSize(12, 12)
        
        self.status_label = QLabel("Disconnected")
        
        self.conn_btn = QPushButton("CONNECT")
        self.conn_btn.setStyleSheet("""
            QPushButton {
                background-color: #27272a; border: 1px solid #3f3f46; color: white; 
                border-radius: 4px; padding: 4px 12px; font-weight: bold; font-size: 12px;
            }
            QPushButton:hover { background-color: #3f3f46; }
        """)
        self.conn_btn.clicked.connect(self.toggle_connection)

        status_layout.addWidget(self.status_dot)
        status_layout.addWidget(self.status_label)
        status_layout.addSpacing(15)
        status_layout.addWidget(self.conn_btn)
        status_layout.setSpacing(10)
        
        # Set initial state
        self.handle_connection_status(False) 

        self.emergency_stop_button = QPushButton("E-STOP")
        self.emergency_stop_button.setObjectName("Stop_Button")
        self.emergency_stop_button.setToolTip("Immediately halts all machine operations (M112).\nThis is not a pause and requires a full reset.")
        
        header_layout.addWidget(title)
        header_layout.addStretch()
        header_layout.addLayout(status_layout)
        header_layout.addSpacing(20)
        header_layout.addWidget(self.emergency_stop_button)
        return header_widget

    def trigger_emergency_stop(self):
        """Immediately halts the machine and alerts the user."""
        self.append_log("EMERGENCY STOP ACTIVATED", "ERROR")
        
        # 1. Primary Action: Halt the machine via G-code
        self.send_command("M112")
        
        # 2. Secondary Action: Stop local timers/sequences
        self.display_page.stop_print_sequence()
        
        # 3. User Feedback: Display a critical message
        msg_box = QMessageBox()
        msg_box.setIcon(QMessageBox.Critical)
        msg_box.setWindowTitle("EMERGENCY STOP")
        msg_box.setText("EMERGENCY STOP ACTIVATED")
        msg_box.setInformativeText("The machine has been sent the M112 Halt command. This is not a pause. A full reset is required.")
        msg_box.setStandardButtons(QMessageBox.Ok)
        msg_box.exec_()

    def create_sidebar(self):
        sidebar_widget = QFrame()
        sidebar_widget.setObjectName("Sidebar")
        sidebar_widget.setFixedWidth(120)
        self.sidebar = sidebar_widget
        
        sidebar_layout = QVBoxLayout(sidebar_widget)
        sidebar_layout.setContentsMargins(15, 15, 15, 15)
        sidebar_layout.setSpacing(15)
        sidebar_layout.setAlignment(Qt.AlignTop | Qt.AlignCenter)

        # Tuples of (Text, icon_name)
        button_defs = [
            ("HOME", "home"), ("UPLOAD", "upload"), ("SETUP", "machine_setup"),
            ("RUN PRINT", "play"), ("DISPLAY", "display")
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
            if text == "JOG":
                self.sidebar.jogBtn = btn
        
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
        self.output_log = log_display # Assign to self
        log_display.setObjectName("Log_Display")
        log_display.setReadOnly(True)

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

    def go_to_run_job(self):
        """
        Gathers data from the setup page, passes it to the run page,
        and then switches to the Run Job page.
        """
        # 2. Update run page with the data from the job_data dictionary
        self.run_page.update_summary()
        
        # 3. Switch to the run page
        run_job_button = self.nav_buttons[3] 
        run_job_button.click()

    def go_to_display_page(self):
        """
        Passes the video file to the display page, switches to it, and starts
        the print sequence.
        """
        # 1. Get the file path from the job_data
        video_path = self.job_data.get('video_path')
        
        # 2. Set the video source on the display page
        if video_path and os.path.exists(video_path):
            self.display_page.set_video_source(video_path)
        else:
            self.display_page.set_video_source(None)

        # 3. Switch to the display page
        display_button = self.nav_buttons[4]
        display_button.click()

        # 4. Start the G-code driven timer and sensor monitoring
        self.display_page.start_print_sequence()


    def closeEvent(self, event):
        """Handle the window close event to ensure graceful shutdown."""
        self.append_log("Closing application...", "INFO")

        if self.is_connected:
            reply = QMessageBox.question(self, 'Confirm Exit', 
                                       "Would you like to shut down the remote machine?",
                                       QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel, 
                                       QMessageBox.Cancel)

            if reply == QMessageBox.Cancel:
                event.ignore()
                return
            elif reply == QMessageBox.Yes:
                self.ssh_worker.shutdown_remote()
        
        self.display_page.cleanup()
        self.ssh_worker.stop()
        self.ssh_worker.wait() # Wait for thread to finish
        event.accept()

if __name__ == '__main__':
    from PyQt5.QtCore import QDateTime
    from PyQt5.QtWidgets import QLineEdit
    
    app = QApplication(sys.argv)
    load_stylesheet(app)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())
