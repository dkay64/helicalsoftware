import os
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QWidget, QLabel, QDoubleSpinBox,
    QFrame, QGridLayout, QRadioButton, QButtonGroup, QSpacerItem, QSizePolicy
)
from PyQt5.QtCore import Qt, pyqtSignal, QSize
from PyQt5.QtGui import QIcon, QFont

class JogDialog(QDialog):
    # This signal is no longer the primary way to send commands, but can be kept for logging/testing
    # jog_command = pyqtSignal(str, str) 

    STYLESHEET = """
        QDialog {
            background-color: #18181b;
            font-family: "Segoe UI";
            font-size: 10pt;
        }
        QLabel {
            color: #e4e4e7;
            font-weight: bold;
        }
        QLabel#Axis_Label {
            color: #a1a1aa;
            font-weight: normal;
        }
        QLabel#DRO_Label {
            color: #22c55e; /* Bright Green */
            font-family: "Consolas", "Monospace";
            font-weight: bold;
            font-size: 12pt;
        }
        QRadioButton {
            color: #a1a1aa;
            padding: 5px;
        }
        QRadioButton::indicator {
            width: 14px;
            height: 14px;
            border-radius: 7px;
            border: 2px solid #52525b;
            background: transparent;
        }
        QRadioButton::indicator:checked {
            background-color: #3b82f6;
            border-color: #3b82f6;
        }
        QDoubleSpinBox {
            background: #27272a;
            border: 1px solid #3f3f46;
            border-radius: 4px;
            color: white;
            padding: 5px;
            min-height: 20px; /* Match button height */
        }
        
        /* --- Control Rack Buttons --- */
        QPushButton#Control_Button {
            background-color: #3f3f46;
            border: 1px solid #52525b;
            border-radius: 4px;
            color: white;
            font-weight: bold;
            font-size: 14pt;
        }
        QPushButton#Control_Button:hover {
            background-color: #52525b;
        }
        QPushButton#Control_Button:pressed {
            background-color: #2563eb;
        }

        /* --- Pill Toggle Buttons --- */
        #Pill_Frame {
            border: 1px solid #3f3f46;
            border-radius: 8px;
            max-height: 30px;
        }
        QPushButton#Pill_Button {
            background-color: #27272a;
            color: #a1a1aa;
            border: none;
            font-size: 9pt;
            font-weight: bold;
        }
        QPushButton#Pill_Button:checked {
            background-color: #3b82f6;
            color: white;
        }
        #Step_Button {
            border-top-left-radius: 7px;
            border-bottom-left-radius: 7px;
        }
        #Jog_Button {
            border-top-right-radius: 7px;
            border-bottom-right-radius: 7px;
        }
    """

    def __init__(self, command_callback=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Jog Control")
        self.setModal(True)
        self.setStyleSheet(self.STYLESHEET)
        
        self.command_callback = command_callback
        self.current_mode = "STEP"
        self.dro_labels = {} # Dictionary to store DRO labels

        self.root_layout = QVBoxLayout(self)
        self.root_layout.setSpacing(15)
        self.root_layout.setContentsMargins(20, 20, 20, 20)

        # --- Settings Section ---
        self.root_layout.addLayout(self.create_settings_controls())
        
        # --- Separator ---
        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setFrameShadow(QFrame.Sunken)
        separator.setStyleSheet("border-color: #27272a;")
        self.root_layout.addWidget(separator)
        
        # --- Control Rack Section ---
        self.root_layout.addLayout(self.create_control_rack())

    def create_settings_controls(self):
        settings_layout = QGridLayout()
        settings_layout.setSpacing(10)
        
        # Mode Toggle
        settings_layout.addWidget(QLabel("Mode"), 0, 0)
        settings_layout.addLayout(self.create_pill_toggle(), 0, 1, 1, 2)

        # Increment Select
        settings_layout.addWidget(QLabel("Step"), 1, 0)
        self.increment_group = QButtonGroup()
        increments = ["0.01mm", "0.1mm", "1mm", "10mm"]
        increment_layout = QHBoxLayout()
        for i, text in enumerate(increments):
            radio_btn = QRadioButton(text)
            self.increment_group.addButton(radio_btn, i)
            increment_layout.addWidget(radio_btn)
            if text == "1mm": radio_btn.setChecked(True)
        settings_layout.addLayout(increment_layout, 1, 1, 1, 2)

        # Feed Rate
        settings_layout.addWidget(QLabel("Feed"), 2, 0)
        self.feed_rate_spinbox = QDoubleSpinBox()
        self.feed_rate_spinbox.setSuffix(" mm/s")
        self.feed_rate_spinbox.setDecimals(1)
        self.feed_rate_spinbox.setMinimum(1)
        self.feed_rate_spinbox.setMaximum(5000)
        self.feed_rate_spinbox.setValue(50)
        settings_layout.addWidget(self.feed_rate_spinbox, 2, 1)

        settings_layout.setColumnStretch(2, 1) # Push everything to the left
        return settings_layout

    def create_pill_toggle(self):
        layout = QHBoxLayout()
        frame = QFrame()
        frame.setObjectName("Pill_Frame")
        pill_layout = QHBoxLayout(frame)
        pill_layout.setContentsMargins(0, 0, 0, 0)
        pill_layout.setSpacing(0)

        self.step_btn = QPushButton("STEP")
        self.step_btn.setObjectName("Pill_Button")
        self.step_btn.setProperty("id", "Step_Button")
        self.step_btn.setCheckable(True)
        self.step_btn.setChecked(True)

        self.jog_btn = QPushButton("JOG")
        self.jog_btn.setObjectName("Pill_Button")
        self.jog_btn.setProperty("id", "Jog_Button")
        self.jog_btn.setCheckable(True)
        
        self.mode_button_group = QButtonGroup(self)
        self.mode_button_group.setExclusive(True)
        self.mode_button_group.addButton(self.step_btn)
        self.mode_button_group.addButton(self.jog_btn)
        self.mode_button_group.buttonClicked.connect(lambda btn: setattr(self, 'current_mode', btn.text()))

        pill_layout.addWidget(self.step_btn)
        pill_layout.addWidget(self.jog_btn)
        
        layout.addWidget(frame)
        return layout

    def create_control_rack(self):
        rack_layout = QVBoxLayout()
        rack_layout.setSpacing(10)
        
        rack_layout.addLayout(self.create_axis_row("R-AXIS", "R"))
        rack_layout.addLayout(self.create_axis_row("T-AXIS", "T"))
        rack_layout.addLayout(self.create_axis_row("Z-AXIS", "Z"))
        
        return rack_layout

    def create_axis_row(self, name, axis_code):
        row_layout = QHBoxLayout()

        label = QLabel(name)
        label.setObjectName("Axis_Label")
        label.setFixedWidth(80)
        label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        dro_label = QLabel("0.00")
        dro_label.setObjectName("DRO_Label")
        dro_label.setMinimumWidth(80) # Give it some space
        self.dro_labels[axis_code] = dro_label

        minus_btn = QPushButton("\u2212") # Minus sign
        minus_btn.setObjectName("Control_Button")
        minus_btn.setFixedSize(45, 40)
        minus_btn.clicked.connect(lambda: self.send_jog(axis_code, -1))

        plus_btn = QPushButton("+")
        plus_btn.setObjectName("Control_Button")
        plus_btn.setFixedSize(45, 40)
        plus_btn.clicked.connect(lambda: self.send_jog(axis_code, 1))

        row_layout.addWidget(label)
        row_layout.addWidget(dro_label) # Add DRO label to layout
        row_layout.addStretch() # Spacer
        row_layout.addWidget(minus_btn)
        row_layout.addWidget(plus_btn)

        return row_layout

    def update_dro(self, r, t, z):
        """Updates the Digital Readout labels with new coordinates."""
        if "R" in self.dro_labels:
            self.dro_labels["R"].setText(f"{r:.2f}")
        if "T" in self.dro_labels:
            self.dro_labels["T"].setText(f"{t:.2f}")
        if "Z" in self.dro_labels:
            self.dro_labels["Z"].setText(f"{z:.2f}")

    def send_jog(self, axis, direction):
        if self.current_mode == "STEP":
            selected_radio = self.increment_group.checkedButton()
            step_size = float(selected_radio.text().replace('mm', '')) if selected_radio else 1.0
        else: # JOG mode
            step_size = 50.0 # Fixed large value

        delta = step_size * direction
        feed_rate_mmpm = self.feed_rate_spinbox.value() * 60

        commands = [
            'G91', # Set to relative positioning
            f'G1 {axis}{delta:.4f} F{feed_rate_mmpm:.1f}',
            'G90'  # Set back to absolute positioning
        ]
        
        for cmd in commands:
            if self.command_callback:
                self.command_callback(cmd)
            else:
                print(f"No callback configured. Command not sent: {cmd}")


if __name__ == '__main__':
    import sys
    from PyQt5.QtWidgets import QApplication
    from PyQt5.QtCore import QTimer
    import random

    app = QApplication(sys.argv)
    
    # Example of how to use the new dialog
    def dummy_command_sender(command):
        print(f"SENT TO BACKEND: {command}")
        
    dialog = JogDialog(command_callback=dummy_command_sender)

    # --- Example DRO Update ---
    coords = {'r': 10.5, 't': -25.1, 'z': 0.0}
    dialog.update_dro(coords['r'], coords['t'], coords['z'])
    
    def simulate_machine_updates():
        coords['r'] += random.uniform(-0.1, 0.1)
        coords['t'] += random.uniform(-0.5, 0.5)
        coords['z'] += random.uniform(-0.01, 0.01)
        dialog.update_dro(coords['r'], coords['t'], coords['z'])

    timer = QTimer()
    timer.timeout.connect(simulate_machine_updates)
    timer.start(100) # Update every 100ms
    
    dialog.exec_()