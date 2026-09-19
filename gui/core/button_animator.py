# gui/core/button_animator.py - Click animation for all control-deck buttons
# Provides visible feedback when any QPushButton is clicked: brief scale + color flash + opacity pulse.
# Installed globally via QApplication eventFilter, so every button in control deck and main window animates
# without needing to subclass each QPushButton.

from PyQt5.QtCore import QObject, QEvent, QPropertyAnimation, QEasingCurve, QTimer
from PyQt5.QtWidgets import QPushButton, QGraphicsOpacityEffect


class ButtonClickAnimator(QObject):
    """
    Global click animator for QPushButton.
    Intercepts MouseButtonPress on any QPushButton and plays a color flash +
    opacity pulse. Geometry bounce was removed (it fought layouts via
    setFixedSize and cost two geometry animations per click).
    Install once on QApplication: QApplication.instance().installEventFilter(animator)
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        # Keep refs to running animations to prevent GC
        self._running = []
        # Cache original stylesheets per button (to restore after flash)
        self._orig_style = {}

    def eventFilter(self, obj, event):
        # Catch button press at app level (single global filter — no per-button
        # filters, which double-fired animate()).
        if isinstance(obj, QPushButton):
            if event.type() == QEvent.MouseButtonPress and event.button() == 1 and obj.isEnabled():
                self.animate(obj)
        return super().eventFilter(obj, event)

    def animate(self, btn: QPushButton):
        if not isinstance(btn, QPushButton) or not btn.isEnabled():
            return
        try:
            # Remember original stylesheet once + purge when button dies (no leak)
            if btn not in self._orig_style:
                self._orig_style[btn] = btn.styleSheet()
                try:
                    btn.destroyed.connect(lambda _=None, b=btn: self._drop_button(b))
                except Exception:
                    pass
            # Style flash + opacity pulse in parallel (no geometry anim).
            self._flash_style(btn)
            self._pulse_opacity(btn)
        except Exception:
            # Fail soft — don't break button functionality
            try:
                self._flash_style(btn)
            except Exception:
                pass

    def _drop_button(self, btn: QPushButton) -> None:
        try:
            self._orig_style.pop(btn, None)
        except Exception:
            pass

    def _flash_style(self, btn: QPushButton):
        try:
            orig = self._orig_style.get(btn, btn.styleSheet())
            # Detect primary (dark) vs neutral
            is_primary = False
            try:
                is_primary = btn.property("primary") is True
                if not is_primary and orig:
                    is_primary = "#111827" in orig or "background:#111827" in orig.replace(" ", "")
                # Also detect control-deck primary quick buttons (Nominal)
                if not is_primary:
                    txt = btn.text().lower()
                    if txt in ("nominal", "apply all", "apply", "start"):
                        # Many dark buttons use #111827 but may be via style, check text
                        pass
            except Exception:
                pass
            # Choose flash color: light blue for neutral, slightly lighter dark for primary
            if is_primary:
                flash = "background:#1f2937; border:1px solid #374151; color:#ffffff;"
            else:
                # Light flash — subtle blue tint
                flash = "background:#dbeafe; border:1px solid #3b82f6; color:#1e40af;"
            # Apply flash
            btn.setStyleSheet(orig + f"\nQPushButton {{ {flash} }}")
            # Restore after 160ms
            QTimer.singleShot(160, lambda: self._restore_style(btn))
        except Exception:
            pass

    def _restore_style(self, btn: QPushButton):
        try:
            orig = self._orig_style.get(btn)
            if orig is not None and btn:
                btn.setStyleSheet(orig)
                # Re-polish to ensure style recomputed
                btn.style().unpolish(btn)
                btn.style().polish(btn)
                btn.update()
        except Exception:
            pass

    def _pulse_opacity(self, btn: QPushButton):
        try:
            # Use GraphicsOpacityEffect for pulse; reuse if exists
            eff = btn.graphicsEffect()
            if not isinstance(eff, QGraphicsOpacityEffect):
                eff = QGraphicsOpacityEffect(btn)
                btn.setGraphicsEffect(eff)
            else:
                # reset
                eff.setOpacity(1.0)
            anim = QPropertyAnimation(eff, b"opacity", btn)
            anim.setDuration(220)
            anim.setStartValue(0.72)
            anim.setEndValue(1.0)
            anim.setEasingCurve(QEasingCurve.OutQuad)
            self._running.append(anim)

            def _finish():
                self._cleanup_anims([anim])
                # Drop the effect so the button paints without compositing.
                try:
                    if btn.graphicsEffect() is eff:
                        btn.setGraphicsEffect(None)
                except Exception:
                    pass

            anim.finished.connect(_finish)
            anim.start(QPropertyAnimation.DeleteWhenStopped)
        except Exception:
            pass

    def _cleanup_anims(self, anims):
        for a in anims:
            try:
                if a in self._running:
                    self._running.remove(a)
            except Exception:
                pass


# Global singleton accessor
_animator_instance = None


def install_global_button_animation(app_or_widget=None):
    """
    Install global click animation on QApplication.
    Call once after QApplication is created, e.g. in gui/main_window.__init__ or main.py.
    Returns the animator instance.
    If app_or_widget is a widget, also installs filter on it for ChildAdded coverage.
    """
    global _animator_instance
    from PyQt5.QtWidgets import QApplication
    app = QApplication.instance()
    target = app if app is not None else app_or_widget
    if target is None:
        return None
    if _animator_instance is None:
        _animator_instance = ButtonClickAnimator(target)
        target.installEventFilter(_animator_instance)
    # NOTE: no per-button install here — the app-level filter already covers
    # all buttons. Per-button filters caused double animate() per click.
    return _animator_instance
