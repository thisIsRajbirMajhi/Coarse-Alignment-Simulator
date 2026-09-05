# gui/windows/control_window.py - Simplified Control Deck window (header removed per user request)

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QMainWindow,
    QScrollArea,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from gui.styles import APP_STYLE


class ControlDashboardWindow(QMainWindow):
    """
    Simplified Control Deck — header removed (no Presets/Search/Apply/Discard/Quick bar).
    Just hosts the control_widget tabs (Global, Beacons, Camera, Control, Environment, Disturbances).
    """

    def __init__(self, main_window, control_widget: QWidget):
        super().__init__(main_window)
        self.main_window = main_window
        self._control_widget = control_widget
        self.setWindowTitle("Control Deck")
        self.setMinimumSize(500, 820)
        self.resize(560, 980)
        self.setStyleSheet(APP_STYLE)

        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: #f9fafb; } QScrollBar:vertical { background:#e5e7eb; width:8px; }")
        scroll.setWidget(control_widget)
        self._scroll = scroll
        root.addWidget(scroll, 1)

        self.setCentralWidget(central)

        sb = QStatusBar()
        sb.setStyleSheet("QStatusBar { background:#ffffff; border-top:1px solid #e5e7eb; } QStatusBar QLabel { color:#6b7280; }")
        sb.showMessage("Control Deck — no presets/header. Use tabs to configure.")
        self.setStatusBar(sb)

        self.setWindowFlags(self.windowFlags() | Qt.Window)

        try:
            from gui.core.button_animator import install_global_button_animation, install_button_animations_for_widget
            install_global_button_animation(self)
            install_button_animations_for_widget(self)
            if self._control_widget is not None:
                install_button_animations_for_widget(self._control_widget)
        except Exception:
            pass

    def closeEvent(self, event):
        event.ignore()
        self.hide()
        if hasattr(self.main_window, "statusBar"):
            self.main_window.statusBar().showMessage("Control Panel hidden — click Show Controls to show", 3000)
