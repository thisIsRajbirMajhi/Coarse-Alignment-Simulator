# tests/test_terminal_panels.py - UI tests for RemoteTerminalPanel and Control Deck (SettingsDialog)
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

QtWidgets = pytest.importorskip("PyQt5.QtWidgets", reason="PyQt5 required")
pytest.importorskip("PyQt5.QtCore")


@pytest.fixture()
def qapp():
    from PyQt5.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_remote_terminal_panel_builds_and_collects(qapp):
    from gui.panels.remote_terminal_panel import RemoteTerminalPanel
    from remote_terminal.config import RemoteTerminalScenarioConfig

    panel = RemoteTerminalPanel()
    cfg = panel.collect_config()
    assert isinstance(cfg, RemoteTerminalScenarioConfig)
    assert cfg.terminal_count >= 1

    # Change count to 3
    panel.count_slider.setValue(3)
    cfg3 = panel.collect_config()
    assert cfg3.terminal_count == 3
    assert len(cfg3.terminals) == 3

    # Switch to second terminal
    panel._select_terminal(1)
    assert panel.id_edit.text() == "RT-002"

    # Set power and beacon
    panel._set_power(False)
    cfg_pwr = panel.collect_config()
    assert cfg_pwr.terminals[1].state.power_state == "OFF"

    # Live telemetry update
    panel.update_telemetry({
        "terminal_count": 3,
        "emitting_count": 2,
        "best_link": "OPTICAL_LOCK",
        "terminals": [
            {"id": "RT-001", "communication_state": "OPTICAL_LOCK", "beacon_state": "EMITTING", "position": (1000, 1000, 0)},
            {"id": "RT-002", "communication_state": "NO_LINK", "beacon_state": "OFF", "position": (1100, 1000, 0)},
            {"id": "RT-003", "communication_state": "DETECTING", "beacon_state": "EMITTING", "position": (900, 1000, 0)},
        ]
    })
    assert "OPTICAL_LOCK" in panel.live_status_badge.text()
    panel.close()


def test_control_deck_fullscreen_toggle(qapp):
    from gui.application.session import SimulationSession
    from gui.views.settings_dialog import SettingsDialog

    session = SimulationSession()
    session.ensure_built()
    dlg = SettingsDialog(session)

    # Check tabs: Remote Terminal is first tab
    assert dlg.tabs.count() == 4
    assert dlg.tabs.tabText(0) == "Remote Terminal"
    assert dlg.tabs.tabText(1) in ("Local Terminal", "Camera")

    # Test fullscreen toggle
    assert dlg.btn_fullscreen.text() == "Full Screen"
    dlg.toggle_fullscreen()
    assert dlg._fullscreen is True
    assert dlg.btn_fullscreen.text() == "Exit Full Screen"

    dlg.toggle_fullscreen()
    assert dlg._fullscreen is False
    assert dlg.btn_fullscreen.text() == "Full Screen"

    # Test sync_from_session
    dlg.sync_from_session(session)
    dlg.close()


def test_remote_terminal_capabilities_persistence(qapp):
    from gui.panels.remote_terminal_panel import RemoteTerminalPanel
    from remote_terminal.config import RemoteTerminalScenarioConfig

    scen = RemoteTerminalScenarioConfig(terminal_count=1).validate()
    scen.terminals[0].communication.capabilities = ["BEACON", "TRACKING"]
    scen.terminals[0].communication.protocol_name = "FREE_SPACE_OPTICAL_v2"

    panel = RemoteTerminalPanel(initial=scen)
    assert panel.cap_beacon.isChecked() is True
    assert panel.cap_track.isChecked() is True
    assert panel.cap_tx.isChecked() is False
    assert panel.cap_rx.isChecked() is False
    assert panel.protocol_edit.text() == "FREE_SPACE_OPTICAL_v2"

    # User modifies checkboxes
    panel.cap_tx.setChecked(True)
    collected = panel.collect_config()
    caps = collected.terminals[0].communication.capabilities
    assert "OPTICAL_TX" in caps
    assert "BEACON" in caps
    assert "TRACKING" in caps
    assert "OPTICAL_RX" not in caps
    panel.close()
