import sys
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QLineEdit,
    QTextEdit, QGroupBox, QFormLayout, QComboBox, QSpinBox, QDoubleSpinBox,
    QGridLayout, QSplitter, QScrollArea, QSizePolicy
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont

class AdvancedPage(QWidget):
    """
    Advanced control page providing direct access to G-code commands,
    machine controls, and a live terminal, with a refined Zinc/Industrial dark theme.
    """
    log_message = pyqtSignal(str, str)

    def __init__(self, main_window=None, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self.setObjectName("AdvancedPage")

        self.splitter = QSplitter(Qt.Horizontal)
        
        controls_widget = self._create_left_column()
        terminal_widget = self._create_right_column()

        self.splitter.addWidget(controls_widget)
        self.splitter.addWidget(terminal_widget)
        
        # Set initial size ratio: 2/3 for controls, 1/3 for terminal
        self.splitter.setSizes([800, 400])

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0,0,0,0)
        layout.addWidget(self.splitter)
        self.setLayout(layout)

        self._apply_styles()

    def send_command(self, command):
        """Helper to safely send a command via the main window."""
        if self.main_window:
            self.main_window.send_command(command)
        else:
            print(f"DEBUG: Command sent: {command}")
    
    def create_timing_group(self):
        group = QGroupBox("Timing / Flow Control")
        layout = QHBoxLayout()
        layout.setSpacing(8)

        g4_label = QLabel("G4 Duration:")
        self.sb_g4_wait = QSpinBox()
        self.sb_g4_wait.setRange(0.1, 3600.0)
        self.sb_g4_wait.setValue(10.0)
        self.sb_g4_wait.setSuffix(" s")
        
        btn_g4 = QPushButton("Send G4 (Pause)")
        btn_g4.clicked.connect(lambda: self.send_command(f"G4 P{self.sb_g4_wait.value()}"))

        btn_g5 = QPushButton("G5 (Wait for RPM)")
        btn_g5.clicked.connect(lambda: self.send_command("G5"))
        
        btn_g6 = QPushButton("G6 (Wait for Metrology)")
        btn_g6.clicked.connect(lambda: self.send_command("G6"))

        layout.addWidget(g4_label)
        layout.addWidget(self.sb_g4_wait)
        layout.addWidget(btn_g4)
        layout.addWidget(btn_g5)
        layout.addWidget(btn_g6)
        
        group.setLayout(layout)
        return group


    def _create_left_column(self):
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll_area.setObjectName("ScrollArea")

        scroll_content = QWidget()
        scroll_content.setObjectName("ScrollContent")
        
        main_vbox = QVBoxLayout(scroll_content)
        main_vbox.setSpacing(15)
        main_vbox.setContentsMargins(10, 10, 10, 10)

        main_vbox.addWidget(self._create_motion_group())
        main_vbox.addWidget(self.create_timing_group())
        main_vbox.addWidget(self.create_machine_control_group())
        main_vbox.addWidget(self._create_projector_control_group())
        main_vbox.addWidget(self._create_sequences_group())
        
        main_vbox.addStretch()
        
        scroll_area.setWidget(scroll_content)
        return scroll_area

    def _create_motion_group(self):
        group = QGroupBox("Motion")
        layout = QFormLayout()
        layout.setSpacing(10)
        
        g0_hbox = QHBoxLayout()
        self.g0_r = QLineEdit(); self.g0_r.setPlaceholderText("R")
        self.g0_t = QLineEdit(); self.g0_t.setPlaceholderText("T")
        self.g0_z = QLineEdit(); self.g0_z.setPlaceholderText("Z")
        g0_hbox.addWidget(self.g0_r)
        g0_hbox.addWidget(self.g0_t)
        g0_hbox.addWidget(self.g0_z)
        g0_button = QPushButton("Send G0")
        g0_button.clicked.connect(lambda: self.send_command(
            f"G0 R{self.g0_r.text()} T{self.g0_t.text()} Z{self.g0_z.text()}".strip()
        ))
        g0_hbox.addWidget(g0_button)
        layout.addRow("G0 (Rapid):", g0_hbox)

        g1_hbox = QHBoxLayout()
        self.g1_r = QLineEdit(); self.g1_r.setPlaceholderText("R")
        self.g1_t = QLineEdit(); self.g1_t.setPlaceholderText("T")
        self.g1_z = QLineEdit(); self.g1_z.setPlaceholderText("Z")
        self.g1_fr = QLineEdit(); self.g1_fr.setPlaceholderText("FR")
        self.g1_ft = QLineEdit(); self.g1_ft.setPlaceholderText("FT")
        self.g1_fz = QLineEdit(); self.g1_fz.setPlaceholderText("FZ")
        g1_hbox.addWidget(self.g1_r)
        g1_hbox.addWidget(self.g1_t)
        g1_hbox.addWidget(self.g1_z)
        g1_hbox.addWidget(self.g1_fr)
        g1_hbox.addWidget(self.g1_ft)
        g1_hbox.addWidget(self.g1_fz)
        g1_button = QPushButton("Send G1")
        g1_button.clicked.connect(lambda: self.send_command(
            (f"G1 R{self.g1_r.text()} T{self.g1_t.text()} Z{self.g1_z.text()} "
             f"FR{self.g1_fr.text()} FT{self.g1_ft.text()} FZ{self.g1_fz.text()}").strip()
        ))
        g1_hbox.addWidget(g1_button)
        layout.addRow("G1 (Linear):", g1_hbox)

        group.setLayout(layout)
        return group

    def create_machine_control_group(self):
        group = QGroupBox("Machine Control")
        v_layout = QVBoxLayout()
        v_layout.setSpacing(10)

        # Row 1 (RPM)
        rpm_hbox = QHBoxLayout()
        rpm_hbox.addWidget(QLabel("A-axis RPM:"))
        self.sb_rpm = QSpinBox()
        self.sb_rpm.setRange(0, 5000)
        rpm_hbox.addWidget(self.sb_rpm)
        btn_g33 = QPushButton("G33 (A RPM)")
        btn_g33.clicked.connect(lambda: self.send_command(f"G33 A{self.sb_rpm.value()}"))
        rpm_hbox.addWidget(btn_g33)
        v_layout.addLayout(rpm_hbox)
        
        # Row 2 (Feed)
        feed_hbox = QHBoxLayout()
        feed_hbox.addWidget(QLabel("Feed Rate (mm/s):"))
        self.sb_feed = QSpinBox()
        self.sb_feed.setRange(1, 1000000)
        self.sb_feed.setValue(100)
        feed_hbox.addWidget(self.sb_feed)
        btn_feed = QPushButton("Set Feed (F)")
        btn_feed.clicked.connect(lambda: self.send_command(f"F{self.sb_feed.value()}"))
        feed_hbox.addWidget(btn_feed)
        v_layout.addLayout(feed_hbox)

        # Row 2 (Motors + G28)
        row2_hbox = QHBoxLayout()
        btn_m17 = QPushButton("M17 Motors On")
        btn_m18 = QPushButton("M18 Motors Off")
        btn_g28 = QPushButton("G28 Home")
        btn_m17.clicked.connect(lambda: self.send_command("M17"))
        btn_m18.clicked.connect(lambda: self.send_command("M18"))
        btn_g28.clicked.connect(lambda: self.send_command("G28"))
        row2_hbox.addWidget(btn_m17)
        row2_hbox.addWidget(btn_m18)
        row2_hbox.addWidget(btn_g28)
        v_layout.addLayout(row2_hbox)
        
        # Row 3 (Modes: G90, G91)
        row3_hbox = QHBoxLayout()
        btn_g90 = QPushButton("G90 Absolute")
        btn_g91 = QPushButton("G91 Relative")
        btn_g90.clicked.connect(lambda: self.send_command("G90"))
        btn_g91.clicked.connect(lambda: self.send_command("G91"))
        row3_hbox.addWidget(btn_g90)
        row3_hbox.addWidget(btn_g91)
        v_layout.addLayout(row3_hbox)

        # Row 4 (Zeroing)
        zero_hbox = QHBoxLayout()
        zero_hbox.addWidget(QLabel("G92 Axis:"))
        self.g92_axis_combo = QComboBox()
        self.g92_axis_combo.addItems(["R", "T", "Z", "X", "Y", "A"])
        self.g92_axis_combo.setStyleSheet("QComboBox QAbstractItemView { background-color: #27272a; border: 1px solid #3f3f46; selection-background-color: #2563eb; color: #e4e4e7; }")
        zero_hbox.addWidget(self.g92_axis_combo)
        btn_zero = QPushButton("G92 Zero Axis")
        btn_zero.clicked.connect(lambda: self.send_command(f"G92 {self.g92_axis_combo.currentText()}"))
        zero_hbox.addWidget(btn_zero)
        v_layout.addLayout(zero_hbox)
        
        group.setLayout(v_layout)
        return group

    def _create_projector_control_group(self):
        group = QGroupBox("Projector Control")
        v_layout = QVBoxLayout()
        v_layout.setSpacing(10)

        # Row 1
        row1_hbox = QHBoxLayout()
        btn_m200 = QPushButton("M200 On")
        btn_m201 = QPushButton("M201 Off")
        btn_m200.clicked.connect(lambda: self.send_command("M200"))
        btn_m201.clicked.connect(lambda: self.send_command("M201"))
        row1_hbox.addWidget(btn_m200)
        row1_hbox.addWidget(btn_m201)
        v_layout.addLayout(row1_hbox)
        
        # Row 2
        row2_hbox = QHBoxLayout()
        btn_m202 = QPushButton("M202 Play")
        btn_m203 = QPushButton("M203 Pause")
        btn_m202.clicked.connect(lambda: self.send_command("M202"))
        btn_m203.clicked.connect(lambda: self.send_command("M203"))
        row2_hbox.addWidget(btn_m202)
        row2_hbox.addWidget(btn_m203)
        v_layout.addLayout(row2_hbox)

        # Row 3 (LED)
        led_hbox = QHBoxLayout()
        led_hbox.addWidget(QLabel("LED Current (mA):"))
        self.led_current_spinbox = QSpinBox()
        self.led_current_spinbox.setRange(0, 30000)
        self.led_current_spinbox.setStyleSheet("padding: 8px;")
        led_hbox.addWidget(self.led_current_spinbox)
        self.btn_set_led = QPushButton("Set Current")
        self.btn_set_led.clicked.connect(lambda: self.send_command(f"M205 S{self.led_current_spinbox.value()}"))
        led_hbox.addWidget(self.btn_set_led)
        v_layout.addLayout(led_hbox)
        
        group.setLayout(v_layout)
        return group

    def _get_g0_start_position(self):
        """Constructs a G0 command string from the G0 axis inputs."""
        axis_widgets = {"R": self.g0_r, "T": self.g0_t, "Z": self.g0_z}
        parts = ["G0"]
        for axis, widget in axis_widgets.items():
            val = widget.text().strip()
            if val:
                parts.append(f"{axis}{val}")
        
        if len(parts) == 1:
            return None
        
        return " ".join(parts)

    def run_start_sequence(self):
        """Runs the standard machine startup sequence."""
        self.append_to_terminal("[INFO] Running Start Sequence...")
        
        g0_cmd = self._get_g0_start_position()
        if not g0_cmd:
            self.append_to_terminal("[ERROR] Start Sequence requires at least one G0 axis value (R, T, or Z).", "ERROR")
            return

        commands = [
            "M17",      # Motors On
            "G28",      # Home all axes
            g0_cmd,     # Move to start position
            "G92",      # Zero all coordinates
            "G33 A9",   # Start A-axis rotation at 9 RPM
            "G5",       # Wait for RPM to stabilize
        ]

        for cmd in commands:
            self.send_command(cmd)

    def run_end_sequence(self):
        """Runs the standard machine shutdown sequence."""
        self.append_to_terminal("[INFO] Running End Sequence...")
        
        commands = [
            "G33 A0",   # Stop A-axis rotation
            "G28",      # Home all axes
            "M18 R T",  # Disable R and T motors
        ]

        for cmd in commands:
            self.send_command(cmd)

    def _create_sequences_group(self):
        group = QGroupBox("Sequences")
        hbox = QHBoxLayout()
        hbox.setSpacing(8)
        
        start_button = QPushButton("Run Start Sequence")
        start_button.clicked.connect(self.run_start_sequence)
        hbox.addWidget(start_button)
        
        end_button = QPushButton("Run End Sequence")
        end_button.clicked.connect(self.run_end_sequence)
        hbox.addWidget(end_button)
        
        group.setLayout(hbox)
        return group

    def _create_right_column(self):
        terminal_widget = QWidget()
        terminal_widget.setObjectName("TerminalWidget")
        layout = QVBoxLayout(terminal_widget)
        layout.setContentsMargins(0, 5, 5, 5)
        layout.setSpacing(5)

        header = QLabel("G-CODE TERMINAL")
        header.setObjectName("TerminalHeader")
        header.setAlignment(Qt.AlignCenter)

        self.log_display = QTextEdit()
        self.log_display.setReadOnly(True)
        self.log_display.setObjectName("TerminalOutput")
        self.log_display.setFont(QFont("Consolas", 10))

        input_hbox = QHBoxLayout()
        self.command_input = QLineEdit()
        self.command_input.setPlaceholderText("Type command...")
        send_button = QPushButton("Send")
        send_button.setObjectName("SendButton")
        
        # Connect signals
        self.command_input.returnPressed.connect(self._handle_manual_send)
        send_button.clicked.connect(self._handle_manual_send)

        input_hbox.addWidget(self.command_input, 1)
        input_hbox.addWidget(send_button)

        layout.addWidget(header)
        layout.addWidget(self.log_display, 1)
        layout.addLayout(input_hbox)
        
        return terminal_widget

    def append_to_terminal(self, text, level=None):
        """Appends a message to the terminal log display."""
        # This page's terminal shows raw logs, so we ignore the level
        # and just append the text.
        self.log_display.append(text)
        self.log_display.verticalScrollBar().setValue(self.log_display.verticalScrollBar().maximum())

    def _handle_manual_send(self):
        """Sends the command from the input box."""
        command = self.command_input.text().strip()
        if command:
            self.send_command(command)
            self.append_to_terminal(f"> {command}")
            self.command_input.clear()

    def _apply_styles(self):
        self.setStyleSheet("""
            /* --- Main Page & Scroll Area --- */
            #AdvancedPage {
                background-color: #18181b;
            }
            QScrollArea {
                border: none;
                background-color: #18181b;
            }
            #ScrollContent {
                background-color: #18181b;
            }
            QWidget, QLabel {
                color: #e4e4e7;
            }

            /* --- GroupBox Styling --- */
            QGroupBox {
                color: #e4e4e7;
                border: 1px solid #3f3f46;
                border-radius: 8px;
                font-weight: bold;
                margin-top: 1ex;
                padding: 15px; 
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top center;
                padding: 0 10px;
                background-color: #18181b;
            }

            /* --- Input Widgets --- */
            QLineEdit, QSpinBox, QComboBox {
                background-color: #27272a;
                border: 1px solid #3f3f46;
                border-radius: 4px;
                color: #e4e4e7;
                padding: 8px;
            }
            QLineEdit:focus, QSpinBox:focus, QComboBox:focus {
                border-color: #2563eb;
            }
            QComboBox::drop-down {
                border-left: 1px solid #3f3f46;
            }

            /* --- Buttons --- */
            QPushButton {
                background-color: #3f3f46;
                border: 1px solid #52525b;
                border-radius: 6px;
                color: #e4e4e7;
                padding: 8px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #52525b;
            }
            QPushButton:pressed {
                background-color: #27272a;
            }

            /* --- Terminal Specifics --- */
            #TerminalWidget {
                background-color: #18181b;
            }
            #TerminalHeader {
                font-size: 14px;
                font-weight: bold;
                color: #a1a1aa;
                padding-bottom: 5px;
            }
            #TerminalOutput {
                background-color: #09090b;
                color: #22c55e;
                border: 1px solid #3f3f46;
                border-radius: 4px;
            }
            #SendButton {
                background-color: #2563eb;
                color: white;
            }
            #SendButton:hover {
                background-color: #1d4ed8;
            }
            
            /* --- Splitter Handle --- */
            QSplitter::handle:horizontal {
                width: 2px;
                background-color: #3f3f46;
            }
            QSplitter::handle:horizontal:hover {
                background-color: #2563eb;
            }
        """)

if __name__ == '__main__':
    app = QApplication(sys.argv)
    win = QMainWindow()
    win.setWindowTitle("Advanced Page Test")
    win.setCentralWidget(AdvancedPage())
    win.setGeometry(100, 100, 1200, 768)
    # The main window background is dark, our page should blend in.
    win.setStyleSheet("background-color: #09090b;")
    win.show()
    sys.exit(app.exec_())
