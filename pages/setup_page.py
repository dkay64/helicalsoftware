import sys
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel,
    QPushButton, QGridLayout, QSizePolicy, QSpinBox, QSpacerItem, QFormLayout,
    QDialog, QDialogButtonBox, QDoubleSpinBox, QScrollArea
)
from PyQt5.QtGui import QFont
from PyQt5.QtCore import Qt, pyqtSignal

# --- Custom Dialog for Homing Values ---
class CustomHomingDialog(QDialog):
    """
    A custom dialog for entering specific X, Y, Z, T coordinates.
    Styled to match the main application's dark theme.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Set Custom Position")
        self.setModal(True)

        main_layout = QVBoxLayout(self)
        form_layout = QFormLayout()
        form_layout.setSpacing(15)

        self.inputs = {
            'X': QDoubleSpinBox(),
            'Y': QDoubleSpinBox(),
            'Z': QDoubleSpinBox(),
            'T': QDoubleSpinBox(),
        }

        for axis, spinbox in self.inputs.items():
            spinbox.setRange(-1000.0, 1000.0)
            spinbox.setDecimals(3)
            spinbox.setSingleStep(0.1)
            form_layout.addRow(f"{axis} Position (mm):", spinbox)
        
        main_layout.addLayout(form_layout)

        # Dialog buttons (Apply/Cancel)
        button_box = QDialogButtonBox()
        apply_button = button_box.addButton("Apply", QDialogButtonBox.AcceptRole)
        apply_button.setObjectName("PrimaryButton")
        cancel_button = button_box.addButton("Cancel", QDialogButtonBox.RejectRole)
        cancel_button.setObjectName("SecondaryButton")

        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)

        main_layout.addWidget(button_box)
        self.apply_styles()

    def getValues(self):
        """Returns the values from the spin boxes as a dictionary."""
        return {axis: spinbox.value() for axis, spinbox in self.inputs.items()}

    def apply_styles(self):
        self.setStyleSheet("""
            QDialog {
                background-color: #18181b;
                border: 1px solid #27272a;
            }
            QLabel, QDoubleSpinBox {
                font-size: 14pt;
                color: #e4e4e7;
            }
            QDoubleSpinBox {
                background-color: #27272a;
                border: 1px solid #3f3f46;
                border-radius: 8px;
                padding: 8px;
            }
            QPushButton {
                font-size: 14pt;
                font-weight: bold;
                border-radius: 8px;
                padding: 12px 24px;
                min-width: 100px;
            }
            QPushButton#PrimaryButton {
                background-color: #3b82f6;
                color: white;
            }
            QPushButton#PrimaryButton:hover {
                background-color: #2563eb;
            }
            QPushButton#SecondaryButton {
                background-color: transparent;
                border: 1px solid #3f3f46;
                color: #e4e4e7;
                font-weight: normal;
            }
            QPushButton#SecondaryButton:hover {
                background-color: #27272a;
            }
        """)

# --- Main Setup Page Widget ---
class SetupPage(QWidget):
    setupCompleted = pyqtSignal()
    log_message = pyqtSignal(str, str)

    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.setObjectName("SetupPage")
        self.main_window = main_window

        # A. Create a top-level layout for the page
        page_layout = QVBoxLayout(self)
        page_layout.setContentsMargins(0, 0, 0, 0)

        # B. Create a scroll area to contain the resizing content
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.NoFrame) # Make it blend in
        page_layout.addWidget(scroll_area)

        # C. Create a container widget for the actual page content
        content_widget = QWidget()
        content_widget.setObjectName("SetupContent")
        scroll_area.setWidget(content_widget)

        # D. This is the main layout for the page content, inside the scroll area
        main_layout = QVBoxLayout(content_widget)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(20)

        # Step 1: Homing
        step1_card = self.create_step_card("STEP 1: HOMING & AXES SETUP", self.create_step1_content())
        main_layout.addWidget(step1_card)

        # Step 2: Parameters
        step3_card = self.create_step_card("STEP 2: SET PARAMETERS", self.create_step3_content())
        main_layout.addWidget(step3_card)

        main_layout.addStretch(1)

        footer_layout = QHBoxLayout()
        footer_layout.addSpacerItem(QSpacerItem(40, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))
        self.next_step_button = QPushButton("NEXT STEP: RUN JOB")
        self.next_step_button.setObjectName("NextStepButton")
        self.next_step_button.clicked.connect(self._on_setup_completed)
        footer_layout.addWidget(self.next_step_button)
        main_layout.addLayout(footer_layout)
        
        self.setLayout(main_layout)
        self.apply_styles()

    def create_step_card(self, title, content_widget):
        """Creates a styled card for a step in the setup process."""
        card = QFrame()
        card.setObjectName("Card")
        card_layout = QVBoxLayout(card)
        card_layout.setSpacing(15)

        header = QLabel(title)
        header.setObjectName("CardHeader")
        card_layout.addWidget(header)

        card_layout.addWidget(content_widget)
        
        return card

    def create_step1_content(self):
        """Content for the homing and axes setup step."""
        content_widget = QWidget()
        card_layout = QHBoxLayout(content_widget)
        card_layout.setSpacing(20)
        card_layout.setContentsMargins(0,0,0,0)

        controls_widget = QWidget()
        controls_layout = QVBoxLayout(controls_widget)
        controls_layout.setSpacing(15)

        home_all_button = QPushButton("HOME ALL")
        home_all_button.setObjectName("PrimaryButton")
        home_all_button.clicked.connect(self._on_home_all_clicked)
        controls_layout.addWidget(home_all_button)

        axis_grid = QGridLayout()
        axes = ['X', 'Y', 'Z', 'T']
        for i, axis in enumerate(axes):
            button = QPushButton(f"Home {axis}")
            button.setObjectName("SecondaryButton")
            button.clicked.connect(lambda _, a=axis: self._send_gcode_command(f'G28 {a}'))
            axis_grid.addWidget(button, i // 2, i % 2)
        controls_layout.addLayout(axis_grid)

        position_frame = QFrame()
        position_frame.setObjectName("ReadoutFrame")
        position_layout = QFormLayout(position_frame)
        self.position_labels = {axis: QLabel("0.00 mm") for axis in axes}
        for axis, label in self.position_labels.items():
            label.setObjectName("PositionLabel")
            position_layout.addRow(f"<b>{axis}:</b>", label)
        controls_layout.addWidget(position_frame)
        controls_layout.addStretch()

        custom_value_button = QPushButton("Custom Value")
        custom_value_button.setObjectName("SecondaryButton")
        custom_value_button.clicked.connect(self.open_custom_value_dialog)
        controls_layout.addWidget(custom_value_button)
        
        diagram_placeholder = QLabel("Axes Diagram")
        diagram_placeholder.setObjectName("DiagramPlaceholder")
        diagram_placeholder.setAlignment(Qt.AlignCenter)
        diagram_placeholder.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        card_layout.addWidget(controls_widget, 1)
        card_layout.addWidget(diagram_placeholder, 1)
        return content_widget

    def create_step3_content(self):
        """Content for the set parameters step."""
        content_widget = QWidget()
        card_layout = QVBoxLayout(content_widget)
        card_layout.setSpacing(15)
        card_layout.setContentsMargins(0,0,0,0)

        form_layout = QFormLayout()
        form_layout.setSpacing(10)
        
        self.rpm_input = QSpinBox()
        self.rpm_input.setRange(0, 5000)
        form_layout.addRow("RPM:", self.rpm_input)
        
        # Changed label and range as requested
        self.laser_power_input = QSpinBox()
        self.laser_power_input.setRange(0, 9999)
        form_layout.addRow("Laser Power:", self.laser_power_input)
        
        card_layout.addLayout(form_layout)

        self.advanced_params_button = QPushButton("Advanced Params")
        self.advanced_params_button.setObjectName("SecondaryButton")
        self.advanced_params_button.setCheckable(True)
        card_layout.addWidget(self.advanced_params_button)

        # --- Advanced Frame populated with 3 inputs ---
        self.advanced_frame = QFrame()
        self.advanced_frame.setObjectName("AdvancedFrame")
        self.advanced_frame.setVisible(False)
        advanced_layout = QFormLayout(self.advanced_frame)
        self.resolution_input = QSpinBox()
        self.feed_rate_input = QSpinBox()
        self.dwell_input = QSpinBox()
        advanced_layout.addRow("Resolution (μm):", self.resolution_input)
        advanced_layout.addRow("Feed Rate (mm/s):", self.feed_rate_input)
        advanced_layout.addRow("Dwell (ms):", self.dwell_input)
        card_layout.addWidget(self.advanced_frame)
        
        self.advanced_params_button.toggled.connect(self.advanced_frame.setVisible)
        
        card_layout.addStretch()
        return content_widget


    def _on_setup_completed(self):
        """Logs the completion and emits the signal."""
        # Validate Laser Power
        power = self.laser_power_input.value()
        if power > 255:
            self.log_message.emit(f"Laser power out of range ({power}). Clamping to 255.", "WARNING")
            self.laser_power_input.setValue(255)
            power = 255
        
        # Store data in the main state manager
        self.main_window.job_data['rpm'] = self.get_rpm()
        self.main_window.job_data['power'] = power
        self.main_window.job_data['feed_rate'] = self.feed_rate_input.value()

        self.log_message.emit("Setup parameters confirmed, proceeding to run job.", "INFO")
        self.setupCompleted.emit()

    def _send_gcode_command(self, command):
        """Helper to send a G-code command via the main window."""
        self.log_message.emit(f"Sending command: {command}", "GCODE")
        if self.main_window:
            self.main_window.send_command(command)

    def _on_home_all_clicked(self):
        """Logs the G-Code for homing all axes."""
        self._send_gcode_command("G28")


    def get_rpm(self):
        """Returns the current value from the RPM input."""
        return self.rpm_input.value()

    def get_laser_power(self):
        """Returns the current value from the laser power input."""
        return self.laser_power_input.value()

    def open_custom_value_dialog(self):
        """Instantiates and opens the new CustomHomingDialog."""
        dialog = CustomHomingDialog(self)
        if dialog.exec_() == QDialog.Accepted:
            values = dialog.getValues()
            self.log_message.emit(f"Custom homing values applied: {values}", "INFO")
            # Example of how to use the values
            for axis, value in values.items():
                if axis in self.position_labels:
                    self.position_labels[axis].setText(f"{value:.2f} mm")

    def apply_styles(self):
        self.setStyleSheet(self.styleSheet() + """
            QWidget#SetupContent {
                background-color: #09090b;
            }
            QFrame#Card {
                background-color: #18181b; border: 1px solid #27272a; border-radius: 12px; padding: 20px;
            }
            QLabel#CardHeader {
                font-size: 18pt; font-weight: bold; color: #e4e4e7; padding-bottom: 10px;
            }
            QLabel, QSpinBox, QDoubleSpinBox {
                font-size: 14pt; color: #e4e4e7;
            }
            QSpinBox, QDoubleSpinBox {
                background-color: #27272a; border: 1px solid #3f3f46; border-radius: 8px; padding: 8px; min-width: 120px;
            }
            QPushButton {
                font-size: 14pt; font-weight: bold; border-radius: 8px; padding: 12px;
            }
            QPushButton#PrimaryButton {
                background-color: #3b82f6; color: white;
            }
            QPushButton#SecondaryButton {
                background-color: transparent; border: 1px solid #3f3f46; color: #e4e4e7; font-weight: normal;
            }
            QPushButton#SecondaryButton:hover, QPushButton#SecondaryButton:checked {
                background-color: #27272a;
            }
            QPushButton#NextStepButton {
                background-color: #3b82f6; color: white; padding: 12px 24px;
            }
            QLabel#DiagramPlaceholder {
                background-color: #27272a; border: 2px dashed #3f3f46; color: #52525b; border-radius: 8px; font-size: 18pt; min-height: 200px;
            }
            QFrame#ReadoutFrame {
                border: 1px solid #27272a; border-radius: 8px; background-color: #09090b;
            }
            QLabel#PositionLabel {
                font-size: 14pt; font-family: 'monospace'; color: #22c55e;
            }
            QFrame#AdvancedFrame {
                background-color: #09090b; border: 1px solid #27272a; border-radius: 8px; margin-top: 5px;
            }
        """)

if __name__ == '__main__':
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    
    # --- Mocking MainWindow for standalone testing ---
    class MockMainWindow(QWidget):
        def __init__(self):
            super().__init__()
            self.job_data = {}
            self.setGeometry(100, 100, 1200, 900)
            self.setStyleSheet("background-color: #09090b;")
            
            layout = QVBoxLayout(self)
            
            # The setup page needs a "main_window" that has a send_command method
            # and a job_data dictionary.
            self.setup_page = SetupPage(main_window=self)
            self.setup_page.log_message.connect(lambda msg, level: print(f"[{level}] {msg}"))
            
            layout.addWidget(self.setup_page)
            self.show()

        def send_command(self, command):
            print(f"SENT G-CODE: '{command}'")

    main_window = MockMainWindow()
    sys.exit(app.exec_())
