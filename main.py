"""
Entry point. Keep this file tiny - it should only launch the GUI.
All real logic belongs in the module packages, not here.
"""

import sys
from PyQt5.QtWidgets import QApplication
from gui.app import MainWindow  # to be implemented in gui/app.py

def main():
    app = QApplication(sys.argv)
    # Install global button click animations (control deck + main window)
    try:
        from gui.core.button_animator import install_global_button_animation
        install_global_button_animation(app)
    except Exception:
        pass
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()