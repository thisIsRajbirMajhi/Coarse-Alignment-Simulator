import os
from datetime import datetime

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QMainWindow,
    QWidget,
    QToolBar,
    QAction,
    QLabel,
    QStatusBar,
    QFileDialog,
    QMessageBox,
)

from gui.styles import APP_STYLE

class DashboardWindow(QMainWindow):
    """
    Separate window for DashboardPanel + GraphPanel.
    Modular sections:
      - Toolbar: Auto-fit, Clear, Export, Help (intuitive icons + tooltips)
      - Central: DashboardPanel (responsive splitter — metrics left, graph right)
      - StatusBar: live summary (FPS, retention, detection) + hints
    Responsive: minimum 900x650, splitter preserves ratio on resize, graph auto-scales.
    Complete picture: graph ViewBox autoRange shows full time history without trimming.
    """

    def __init__(self, main_window, dashboard_panel: QWidget):
        super().__init__(main_window)
        self.main_window = main_window
        self.dashboard_panel = dashboard_panel
        self.setWindowTitle("FSOC — Dashboard (Live Telemetry)")
        self.setMinimumSize(960, 680)
        self.resize(1280, 880)
        self.setStyleSheet(APP_STYLE)
        # Allow prominent title + resizable
        self.setWindowFlags(self.windowFlags() | Qt.Window)

        self._build_toolbar()
        self._build_central()
        self._build_status()

    # Toolbar — intuitive actions

    def _build_toolbar(self):
        tb = QToolBar("Dashboard Tools")
        tb.setMovable(False)
        tb.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        tb.setStyleSheet("QToolBar { background:#ffffff; border-bottom:1px solid #e5e7eb; spacing:8px; padding:6px 8px; } QToolBar QToolButton { background:#ffffff; border:1px solid #e5e7eb; border-radius:4px; padding:5px 12px; font-weight:500; } QToolBar QToolButton:hover { background:#f9fafb; border-color:#d1d5db; color:#111827; }")
        self.addToolBar(Qt.TopToolBarArea, tb)

        act_fit = QAction("Auto-fit", self)
        act_fit.setToolTip("Auto-scale graph to show complete history — responsive, shows full mission timeline")
        act_fit.triggered.connect(self._on_autofit)
        tb.addAction(act_fit)
        act_clear = QAction("Clear", self)
        act_clear.setToolTip("Clear graph history (metrics continue)")
        act_clear.triggered.connect(self._on_clear)
        tb.addAction(act_clear)
        tb.addSeparator()
        act_export = QAction("Export", self)
        act_export.setToolTip("Export current metrics to CSV/JSON")
        act_export.triggered.connect(self._on_export)
        tb.addAction(act_export)
        act_help = QAction("Help", self)
        act_help.setToolTip("Dashboard: left = live values, right = responsive auto-scaling graph")
        act_help.triggered.connect(self._on_help)
        tb.addAction(act_help)

        self.toolbar = tb

    # Central — responsive DashboardPanel

    def _build_central(self):
        # DashboardPanel already contains its own splitter (metrics | graph)
        # Make it central and ensure responsive size policy
        self.dashboard_panel.setParent(self)
        self.setCentralWidget(self.dashboard_panel)
        # Enable responsive resizing: dashboard_panel's internal splitter will handle
        self.dashboard_panel.setStyleSheet(self.dashboard_panel.styleSheet() + " QSplitter::handle { background:#e5e7eb; }")

    # StatusBar — informative live hint

    def _build_status(self):
        sb = QStatusBar()
        sb.setStyleSheet("QStatusBar { background:#ffffff; color:#6b7280; border-top:1px solid #e5e7eb; }")
        self.status_lbl = QLabel("Live — graph auto-scales to show complete history. Drag to pan, scroll to zoom, double-click to fit.")
        self.status_lbl.setStyleSheet("color:#6b7280; font-size:10px;")
        sb.addWidget(self.status_lbl, 1)
        self.live_lbl = QLabel("FPS —  |  Retention —  |  Detection —")
        self.live_lbl.setStyleSheet("color:#111827; font-weight:500; font-size:10px; background:#f9fafb; border:1px solid #e5e7eb; border-radius:4px; padding:2px 6px;")
        sb.addPermanentWidget(self.live_lbl)
        self.setStatusBar(sb)
        self.statusBar().showMessage("Dashboard ready — live metrics update every tick (~30 Hz)", 4000)

    # Actions

    def _on_autofit(self):
        try:
            if hasattr(self.dashboard_panel, "graph"):
                self.dashboard_panel.graph.plot.enableAutoRange()
                self.dashboard_panel.graph.plot.getViewBox().updateAutoRange()
            elif hasattr(self.dashboard_panel, "plot_widget"):
                self.dashboard_panel.plot_widget.enableAutoRange()
        except Exception:
            pass
        self.statusBar().showMessage("Auto-fitted — complete picture visible (no trimming)", 2000)

    def _on_clear(self):
        try:
            if hasattr(self.dashboard_panel, "reset_history"):
                self.dashboard_panel.reset_history()
            elif hasattr(self.dashboard_panel, "graph"):
                self.dashboard_panel.graph.clear()
        except Exception:
            pass
        self.statusBar().showMessage("Graph cleared — history reset, metrics continue", 2000)

    def _on_export(self):
        QMessageBox.information(self, "Export", "Logging has been removed — no data to export.")

    def _on_help(self):
        QMessageBox.information(
            self,
            "Dashboard Help — Intuitive & Informative",
            (
                "LEFT: 4 groups (per spec)\n"
                "  • Dashboard: FPS, Duration (S), Acquisition (S), Proc. Time (S)\n"
                "  • Tracking: Average / Maximum Tracking Error (%) — 15px=100% (color: green<25 yellow<60 red)\n"
                "  • Locking: Status (dot color), Retention Rate (%), Total Acquisitions\n"
                "  • Detection / Searching / Center: Rate (%) + Time (S)\n\n"
                "RIGHT: Responsive graph (Simulation Time vs Value)\n"
                "  • 6 curves: FPS (blue), Retention green, Error red, Center amber, Detection violet, Searching gray\n"
                "  • Auto-scaling: ViewBox autoRange shows complete history without trimming\n"
                "  • Interactive: drag pan, scroll zoom, double-click auto-fit, legend toggles\n"
                "  • Informative: X 0→now (s), Y 0–100 (%), header shows live range\n\n"
                "All values live at ~30 Hz (graph throttled to 8 Hz for responsiveness)."
            ),
        )

    # Live status update (called by MainWindow._update_stats if desired)

    def update_live_status(self, summary: dict):
        """Optional hook for MainWindow to push live FPS/retention into status bar."""
        try:
            fps = summary.get("fps", "-")
            ret = summary.get("lock_retention_rate_pct", "-")
            det = summary.get("detection_rate_pct", "-")
            self.live_lbl.setText(f"FPS {fps}  ·  Retention {ret}%  ·  Detection {det}%")
        except Exception:
            pass

    # Window behavior — hide on close (preserve wiring)

    def closeEvent(self, event):
        event.ignore()
        self.hide()
        if hasattr(self.main_window, "statusBar"):
            self.main_window.statusBar().showMessage("Dashboard hidden — click Show Dashboard to show", 3000)

    def showEvent(self, event):
        super().showEvent(event)
        # Ensure graph auto-fits on show for complete picture
        try:
            self._on_autofit()
        except Exception:
            pass