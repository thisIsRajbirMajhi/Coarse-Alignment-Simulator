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
        assert dlg.tabs.count() == 7
        assert dlg.tabs.tabText(0) == "Presets"
        assert dlg.tabs.tabText(1) == "Remote Terminal"
        assert dlg.tabs.tabText(2) == "Local Terminal"
        assert dlg.tabs.tabText(3) == "Environment"
        assert dlg.tabs.tabText(4) == "Disturbances"
        assert dlg.tabs.tabText(5) == "Camera & PTZ"
        assert dlg.tabs.tabText(6) == "PID Controller"
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


def test_panel_randomize_terminals_button(qapp):
    from gui.panels.remote_terminal_panel import RemoteTerminalPanel
    from remote_terminal.config import FormationShape, RemoteScenarioConfig

    panel = RemoteTerminalPanel()
    emitted = []
    panel.configChanged.connect(emitted.append)
    panel.btn_randomize_terminals.click()
    assert len(emitted) == 1  # exactly one validated config emitted
    cfg = emitted[0]
    assert isinstance(cfg, RemoteScenarioConfig)
    cfg.validate()  # valid by construction
    assert 1 <= cfg.formation.terminal_count <= 8
    if cfg.formation.terminal_count == 1:
        assert cfg.formation.formation_shape == FormationShape.SINGLE
    else:
        assert cfg.formation.formation_shape != FormationShape.SINGLE
    assert 0.0 <= cfg.formation.speed_mps <= 100.0
    assert -180.0 <= cfg.formation.heading_deg <= 180.0
    assert 10.0 <= cfg.formation.terminal_spacing_m <= 500.0
    ids = [t.terminal_id for t in cfg.terminals]
    assert len(set(ids)) == len(ids)  # unique
    for t in cfg.terminals:
        assert t.optical_power_w >= 0.1
        assert t.wavelength_nm in (850.0, 980.0, 1064.0, 1310.0, 1550.0)
        assert t.spot_size_mrad > 0
    # Widgets reflect the randomized config.
    assert panel.spin_count.value() == cfg.formation.terminal_count
    panel.close()


def test_panel_randomize_method_quiet(qapp):
    from gui.panels.remote_terminal_panel import RemoteTerminalPanel

    panel = RemoteTerminalPanel()
    emitted = []
    panel.configChanged.connect(emitted.append)
    cfg = panel.randomize(emit=False)
    cfg.validate()
    assert emitted == []
    assert panel.spin_count.value() == cfg.formation.terminal_count
    panel.close()


def _make_deck(qapp):
    from gui.application.session import SimulationSession
    from gui.views.settings_dialog import SettingsDialog
    session = SimulationSession()
    session.ensure_built()
    return session, SettingsDialog(session)


def test_dialog_randomize_all_covers_remote(qapp):
    session, dlg = _make_deck(qapp)
    try:
        remote, env, dist = [], [], []
        dlg.remoteTerminalChanged.connect(remote.append)
        dlg.environmentChanged.connect(env.append)
        dlg.disturbancesChanged.connect(dist.append)
        dlg.btn_randomize.click()
        assert len(remote) == 1
        assert len(env) == 1
        assert len(dist) == 1
        remote[0].validate()
    finally:
        dlg.close()


def test_dialog_scope_menu_randomizes_remote_only(qapp):
    session, dlg = _make_deck(qapp)
    try:
        remote, env, dist = [], [], []
        dlg.remoteTerminalChanged.connect(remote.append)
        dlg.environmentChanged.connect(env.append)
        dlg.disturbancesChanged.connect(dist.append)
        actions = {a.text(): a for a in dlg.btn_randomize_scope.menu().actions()}
        assert "Remote Terminal" in actions
        actions["Remote Terminal"].trigger()
        assert len(remote) == 1
        assert env == [] and dist == []
    finally:
        dlg.close()


def test_dialog_reset_defaults_restores_all_panels(qapp):
    session, dlg = _make_deck(qapp)
    try:
        # Dirty every panel first.
        _set_shape(dlg.remote_panel, "line")
        dlg.remote_panel.spin_count.setValue(3)
        dlg.env_panel.slider_seed.setValue(123456)
        dlg.dist_panel.slider_turbulence.setValue(5)
        remote, env, dist = [], [], []
        dlg.remoteTerminalChanged.connect(remote.append)
        dlg.environmentChanged.connect(env.append)
        dlg.disturbancesChanged.connect(dist.append)
        dlg.btn_reset_defaults.click()
        assert len(remote) == 1 and len(env) == 1 and len(dist) == 1
        assert dlg.remote_panel.spin_count.value() == 1
        assert dlg.remote_panel.combo_shape.currentData() == "single"
        assert dlg.remote_panel.collect_config().formation.terminal_count == 1
        assert dlg.env_panel.slider_seed.value() == 42
        assert dlg.dist_panel.slider_turbulence.value() == 0
    finally:
        dlg.close()


def test_no_theme_toggle_button(qapp):
    from PyQt5.QtWidgets import QApplication
    from gui.main_window import MainWindow
    import gui.theme as theme_mod

    assert not hasattr(theme_mod, "toggle_theme")
    assert not hasattr(theme_mod, "current_theme")
    w = MainWindow()
    try:
        assert not hasattr(w.controls, "btn_theme")
    finally:
        w.close()
