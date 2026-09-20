# tests/test_lifecycle_buttons.py - Start/Stop/Pause/Reset transitions + error handling.
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

QtWidgets = pytest.importorskip("PyQt5.QtWidgets", reason="PyQt5 required")
pytest.importorskip("PyQt5.QtCore")


@pytest.fixture()
def app():
    from PyQt5.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def controller(app):
    from gui.application.controller import ApplicationController
    from gui.application.session import SimulationSession
    c = ApplicationController(SimulationSession())
    yield c
    try:
        c.stop()
    except Exception:
        pass


def _emissions(c):
    seen = []
    c.stateChanged.connect(lambda v: seen.append(v))
    return seen


def test_start_is_idempotent(controller):
    from gui.application.state import LifecycleState
    assert controller.start() is True
    assert controller.lifecycle == LifecycleState.RUNNING
    seen = _emissions(controller)
    assert controller.start() is False  # already RUNNING: no-op
    assert seen == []
    assert controller.lifecycle == LifecycleState.RUNNING


def test_stop_is_idempotent(controller):
    from gui.application.state import LifecycleState
    controller.start()
    assert controller.stop() is True
    assert controller.lifecycle == LifecycleState.STOPPED
    seen = _emissions(controller)
    assert controller.stop() is False  # already STOPPED: no-op, no signal
    assert seen == []


def test_pause_resume_invalid_transitions_are_noops(controller):
    from gui.application.state import LifecycleState
    seen = _emissions(controller)
    assert controller.pause() is False  # STOPPED
    assert controller.resume() is False  # STOPPED
    assert controller.toggle_pause() is False  # STOPPED
    assert seen == []
    controller.start()
    assert controller.resume() is False  # RUNNING: resume is a no-op
    assert controller.pause() is True
    assert controller.lifecycle == LifecycleState.PAUSED
    assert controller.pause() is False  # already PAUSED
    assert controller.resume() is True
    assert controller.toggle_pause() is True  # RUNNING -> PAUSED
    assert controller.lifecycle == LifecycleState.PAUSED
    assert controller.toggle_pause() is True  # PAUSED -> RUNNING
    assert controller.lifecycle == LifecycleState.RUNNING


def test_start_failure_enters_error_with_message(controller, monkeypatch):
    from gui.application.state import LifecycleState
    errors = []
    controller.errorRaised.connect(lambda m: errors.append(m))
    monkeypatch.setattr(controller.session, "ensure_built",
                        lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    assert controller.start() is False
    assert controller.lifecycle == LifecycleState.ERROR
    assert controller.last_error is not None and "boom" in controller.last_error
    assert errors and "boom" in errors[-1]
    # Recovery via Stop clears the error without rebuilding.
    assert controller.stop() is True
    assert controller.lifecycle == LifecycleState.STOPPED
    assert controller.last_error is None


def test_start_from_error_forces_full_rebuild(controller, monkeypatch):
    from gui.application.state import LifecycleState
    monkeypatch.setattr(controller.session, "ensure_built",
                        lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    assert controller.start() is False
    assert controller.lifecycle == LifecycleState.ERROR
    # ensure_built alone would now succeed but the session may still be
    # broken — start() must call build(), not ensure_built().
    monkeypatch.setattr(controller.session, "ensure_built", lambda: None)
    built = []
    orig_build = controller.session.build
    def spy_build():
        built.append(1)
        return orig_build()
    monkeypatch.setattr(controller.session, "build", spy_build)
    assert controller.start() is True
    assert controller.lifecycle == LifecycleState.RUNNING
    assert len(built) == 1
    assert controller.last_error is None


def test_step_failure_enters_error_and_recovers(controller, monkeypatch):
    from gui.application.state import LifecycleState
    controller.start()
    controller.step()
    assert controller._frames >= 1
    monkeypatch.setattr(controller.session, "step",
                        lambda dt: (_ for _ in ()).throw(ValueError("bad frame")))
    errors = []
    controller.errorRaised.connect(lambda m: errors.append(m))
    controller.step()
    assert controller.lifecycle == LifecycleState.ERROR
    assert controller.last_error is not None and "bad frame" in controller.last_error
    assert errors
    # Further steps are refused while in ERROR (no exception, no progress).
    frames = controller._frames
    controller.step()
    assert controller._frames == frames


def test_reset_restart_semantics(controller):
    from gui.application.state import LifecycleState
    controller.start()
    controller.step()
    assert controller.reset() is True  # RUNNING stays RUNNING
    assert controller.lifecycle == LifecycleState.RUNNING
    assert controller._frames == 0 and controller.duration_s == 0.0
    controller.pause()
    assert controller.reset() is True  # PAUSED lands on STOPPED
    assert controller.lifecycle == LifecycleState.STOPPED


def test_full_reset_replaces_session(controller):
    from gui.application.state import LifecycleState
    controller.start()
    controller.step()
    old = controller.session
    assert controller.full_reset() is True
    assert controller.session is not old
    assert controller.lifecycle == LifecycleState.STOPPED
    assert controller._frames == 0 and controller.duration_s == 0.0
    assert controller.last_error is None


def test_apply_config_unknown_section_warns_without_lifecycle_change(controller):
    from gui.application.commands import ApplyConfigCommand
    from gui.application.state import LifecycleState
    from unittest.mock import sentinel
    errors = []
    controller.errorRaised.connect(lambda m: errors.append(m))
    controller.start()
    controller.apply_config(ApplyConfigCommand(section="nope", config=sentinel.cfg))
    assert controller.lifecycle == LifecycleState.RUNNING  # unchanged
    assert errors and "nope" in errors[-1]
    assert controller.last_error is not None


def test_error_button_states_allow_recovery(controller, monkeypatch):
    from gui.application.state import LifecycleState
    monkeypatch.setattr(controller.session, "ensure_built",
                        lambda: (_ for _ in ()).throw(RuntimeError("x")))
    controller.start()
    states = controller.button_states()
    assert states == {"start": True, "stop": False, "pause": False, "reset": True, "pause_text": "Pause"}


def test_statusbar_latches_error_until_recovery(app):
    from PyQt5.QtWidgets import QApplication
    from gui.main_window import MainWindow
    from gui.application.state import LifecycleState
    w = MainWindow()
    try:
        c = w.controller
        c._fail("simulated fault")
        w._refresh_status_bar()
        msg = w._statusbar.currentMessage()
        assert "ERROR" in msg and "simulated fault" in msg
        assert c.lifecycle == LifecycleState.ERROR
        c.stop()
        w._refresh_status_bar()
        assert "ERROR" not in w._statusbar.currentMessage()
    finally:
        w.close()
