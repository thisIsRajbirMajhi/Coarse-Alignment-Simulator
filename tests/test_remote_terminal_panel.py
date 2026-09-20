# tests/test_remote_terminal_panel.py - RemoteTerminalPanel + Control Deck integration.
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

QtWidgets = pytest.importorskip("PyQt5.QtWidgets", reason="PyQt5 required")
pytest.importorskip("PyQt5.QtCore")


@pytest.fixture()
def qapp():
    from PyQt5.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_panel_builds_and_collects(qapp):
    from gui.panels.remote_terminal_panel import RemoteTerminalPanel
    from remote_terminal.config import RemoteScenarioConfig

    panel = RemoteTerminalPanel()
    cfg = panel.collect_config()
    assert isinstance(cfg, RemoteScenarioConfig)
    assert cfg.formation.terminal_count == 1
    assert len(cfg.terminals) == 1
    panel.close()


def _set_shape(panel, value: str) -> None:
    from remote_terminal.config import FormationShape
    panel.combo_shape.setCurrentIndex(panel.combo_shape.findData(value))
    assert panel.combo_shape.currentData() == value


def test_panel_count_change_resizes_terminals(qapp):
    from gui.panels.remote_terminal_panel import RemoteTerminalPanel

    panel = RemoteTerminalPanel()
    _set_shape(panel, "line")  # SINGLE requires count == 1: pick a shape first
    panel.spin_count.setValue(3)
    cfg = panel.collect_config()
    assert cfg.formation.terminal_count == 3
    assert [t.terminal_id for t in cfg.terminals] == ["RT-001", "RT-002", "RT-003"]
    panel.spin_count.setValue(1)
    assert len(panel.collect_config().terminals) == 1
    panel.close()


def test_panel_per_terminal_edit(qapp):
    from gui.panels.remote_terminal_panel import RemoteTerminalPanel

    panel = RemoteTerminalPanel()
    _set_shape(panel, "line")
    panel.spin_count.setValue(2)
    panel.combo_terminal.setCurrentIndex(1)
    assert panel.edit_tid.text() == "RT-002"
    panel.chk_power.setChecked(False)
    panel.spin_opt_power.setValue(2.5)
    cfg = panel.collect_config()
    assert cfg.terminals[1].power_enabled is False
    assert cfg.terminals[1].optical_power_w == pytest.approx(2.5)
    assert cfg.terminals[0].power_enabled is True  # untouched terminal kept
    panel.close()


def test_panel_invalid_input_blocks_emit(qapp):
    from gui.panels.remote_terminal_panel import RemoteTerminalPanel

    panel = RemoteTerminalPanel()
    emitted = []
    panel.configChanged.connect(emitted.append)
    _set_shape(panel, "line")
    panel.spin_count.setValue(2)
    assert len(emitted) == 2  # shape change + count change
    # Duplicate the ID of terminal 2 -> validation must fail visibly.
    panel.combo_terminal.setCurrentIndex(1)
    assert len(emitted) == 3  # shape + count + terminal switch, all valid
    panel.edit_tid.setText("RT-001")
    panel.edit_tid.editingFinished.emit()
    # Note: isVisible() is False until the panel itself is shown; assert the
    # explicit shown-state flag plus the message instead.
    assert not panel.error_label.isHidden()
    assert "duplicated" in panel.error_label.text()
    assert len(emitted) == 3  # invalid config never emitted
    with pytest.raises(ValueError, match="duplicated"):
        panel.collect_config()
    panel.close()


def test_panel_telemetry_render(qapp):
    from gui.panels.remote_terminal_panel import RemoteTerminalPanel
    from remote_terminal import RemoteTerminalManager, make_default_scenario

    panel = RemoteTerminalPanel()
    mgr = RemoteTerminalManager(make_default_scenario(1), bounds=(2000, 2000), seed=2)
    mgr.update(1.0)
    panel.update_telemetry(mgr.get_telemetry())
    assert "X" in panel.tele_labels["position"].text()
    assert "#" in panel.tele_labels["beacon"].text()
    panel.update_telemetry({})  # empty / malformed input never raises
    panel.update_telemetry(None)
    panel.close()


def test_control_deck_hosts_remote_terminal_tab(qapp):
    from gui.application.session import SimulationSession
    from gui.views.settings_dialog import SettingsDialog

    session = SimulationSession()
    session.ensure_built()
    dlg = SettingsDialog(session)
    try:
        assert dlg.tabs.count() == 3
        assert dlg.tabs.tabText(0) == "Remote Terminal"
        assert dlg.tabs.tabText(1) == "Environment"
        assert dlg.tabs.tabText(2) == "Disturbances"
        dlg.sync_from_session(session)
        assert dlg.remote_panel.spin_count.value() >= 1
    finally:
        dlg.close()


def test_control_deck_remote_signal_and_telemetry(qapp):
    from gui.application.session import SimulationSession
    from gui.views.settings_dialog import SettingsDialog

    session = SimulationSession()
    session.ensure_built()
    dlg = SettingsDialog(session)
    try:
        received = []
        dlg.remoteTerminalChanged.connect(received.append)
        dlg.remote_panel.spin_speed.setValue(25.0)
        assert len(received) == 1
        assert received[0].formation.speed_mps == pytest.approx(25.0)
        snap = session.step(1 / 30)
        dlg.update_telemetry({"terminals": snap.terminals})
        assert "X" in dlg.remote_panel.tele_labels["position"].text()
    finally:
        dlg.close()


def test_terminal_switch_reverts_on_invalid_editor(qapp):
    from gui.panels.remote_terminal_panel import RemoteTerminalPanel

    panel = RemoteTerminalPanel()
    _set_shape(panel, "line")
    panel.spin_count.setValue(2)
    # Corrupt terminal 1's ID (duplicates terminal 2's future value is not
    # possible yet — instead make the editor unreadable-valid): first switch
    # to terminal 2 and duplicate terminal 1's ID there, then try to switch
    # back while terminal 2's editor is invalid.
    panel.combo_terminal.setCurrentIndex(1)
    panel.edit_tid.setText("RT-001")  # duplicate -> editor invalid
    panel.combo_terminal.setCurrentIndex(0)  # attempt switch away
    # Switch is refused: still editing terminal 2, error shown.
    assert panel.combo_terminal.currentIndex() == 1
    assert "duplicated" in panel.error_label.text()
    panel.close()


def test_minimap_overlay_draws_terminals():
    import numpy as np
    from gui.core.renderer import Renderer
    from remote_terminal import RemoteTerminalManager, make_default_scenario

    mgr = RemoteTerminalManager(make_default_scenario(2), bounds=(400, 300), seed=4)
    mgr.update(0.5)
    thumb = np.zeros((300, 400, 3), dtype=np.uint8)
    marked = Renderer.render_minimap_cached(
        thumb, camera=None, label_size=(400, 300), scene_size=(400, 300),
        terminals=mgr.get_telemetry(),
    )
    assert marked.sum() > 0  # markers + labels drawn
    plain = Renderer.render_minimap_cached(
        thumb, camera=None, label_size=(400, 300), scene_size=(400, 300))
    assert marked.sum() > plain.sum()
    Renderer.render_minimap_cached(thumb, camera=None, terminals=None)  # never raises
    Renderer.render_minimap_cached(thumb, camera=None, terminals={"terminals": "junk"})


def test_presenter_reports_remote_diagnostics():
    from gui.application.controller import ApplicationController
    from gui.application.session import SimulationSession
    from gui.presentation.simulation_presenter import SimulationPresenter

    session = SimulationSession(seed=11)
    session.ensure_built()
    controller = ApplicationController(session)
    controller.start()
    for _ in range(4):
        controller.step()
    snap = controller._last_snapshot
    assert snap is not None and snap.terminals is not None
    state = SimulationPresenter().update(snap, session, controller)
    assert state.target_id == "RT-001"
    assert state.beacon_state == "EMITTING"
    assert state.link_state in ("BEACONING", "LINKED", "EMITTING")
