"""
Entry point. Keep this file tiny - it should only launch the GUI.
All real logic belongs in the module packages, not here.
"""

import sys
from PyQt5.QtWidgets import QApplication
from gui.app import MainWindow  # to be implemented in gui/app.py


def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
