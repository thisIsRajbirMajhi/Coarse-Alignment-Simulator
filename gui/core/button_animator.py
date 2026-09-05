# gui/core/button_animator.py - Click animation for all control-deck buttons
# Provides visible feedback when any QPushButton is clicked: brief scale + color flash + opacity pulse.
# Installed globally via QApplication eventFilter, so every button in control deck and main window animates
# without needing to subclass each QPushButton.

from PyQt5.QtCore import QObject, QEvent, QPropertyAnimation, QEasingCurve, QTimer, QRect
from PyQt5.QtWidgets import QPushButton, QGraphicsOpacityEffect


class ButtonClickAnimator(QObject):
    """
    Global click animator for QPushButton.
    Intercepts MouseButtonPress on any QPushButton and plays:
      - geometry shrink (1px inset) 70ms OutQuad → bounce back 110ms OutBounce
      - background flash (light blue for neutral, darker for primary) 160ms
      - opacity pulse 0.72 → 1.0 220ms OutQuad
    Install once on QApplication: QApplication.instance().installEventFilter(animator)
    Also installs per-button to catch ChildAdded for future buttons.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        # Keep refs to running animations to prevent GC
        self._running = []
        # Cache original stylesheets per button (to restore after flash)
        self._orig_style = {}

    def eventFilter(self, obj, event):
        # Catch button press at app level
        if isinstance(obj, QPushButton):
            if event.type() == QEvent.MouseButtonPress and event.button() == 1 and obj.isEnabled():
                self.animate(obj)
            elif event.type() == QEvent.ChildAdded:
                # For containers, ensure new buttons get filter too (app filter already covers)
                pass
        return super().eventFilter(obj, event)

    def animate(self, btn: QPushButton):
        if not isinstance(btn, QPushButton) or not btn.isEnabled():
            return
        # Guard against re-entrancy: if already animating, restart
        try:
            # Remember original stylesheet once
            if btn not in self._orig_style:
                self._orig_style[btn] = btn.styleSheet()

            # 1) Geometry bounce (shrink then expand) — safe for layout-managed widgets
            # Use fixed size trick to allow geometry animation without layout fighting
            orig_geo = btn.geometry()
            # Only animate if button is visible and has valid geometry
            if orig_geo.width() < 10 or orig_geo.height() < 10:
                # Fallback to style flash only
                self._flash_style(btn)
                self._pulse_opacity(btn)
                return

            # Keep original fixed size hints to allow animation
            # Temporarily fix size so layout doesn't fight animation
            btn.setFixedSize(orig_geo.size())
            shrink_geo = QRect(orig_geo.x() + 1, orig_geo.y() + 1, max(10, orig_geo.width() - 2), max(10, orig_geo.height() - 2))

            anim1 = QPropertyAnimation(btn, b"geometry", btn)
            anim1.setDuration(70)
            anim1.setStartValue(orig_geo)
            anim1.setEndValue(shrink_geo)
            anim1.setEasingCurve(QEasingCurve.OutQuad)

            anim2 = QPropertyAnimation(btn, b"geometry", btn)
            anim2.setDuration(110)
            anim2.setStartValue(shrink_geo)
            anim2.setEndValue(orig_geo)
            anim2.setEasingCurve(QEasingCurve.OutBack)
            # Chain
            def _start_second():
                # ensure button still exists
                try:
                    if btn and btn.isVisible():
                        anim2.start()
                except Exception:
                    pass
                # release fixed size after bounce
                QTimer.singleShot(120, lambda: self._release_fixed(btn))

            anim1.finished.connect(_start_second)
            # Keep refs
            self._running.extend([anim1, anim2])
            anim1.start()
            # Cleanup after
            anim2.finished.connect(lambda: self._cleanup_anims([anim1, anim2]))

            # 2) Style flash + opacity pulse in parallel
            self._flash_style(btn)
            self._pulse_opacity(btn)

        except Exception:
            # Fail soft — don't break button functionality
            try:
                self._flash_style(btn)
            except Exception:
                pass

    def _release_fixed(self, btn: QPushButton):
        try:
            # Release fixed size constraint so layout can manage again
            # Use QWIDGETSIZE_MAX equivalent: 16777215
            btn.setMinimumSize(0, 0)
            btn.setMaximumSize(16777215, 16777215)
            btn.setFixedSize(btn.sizeHint())
            # Force layout update
            btn.updateGeometry()
            # After next layout pass, ensure layout flexible (no fixed constraint retained)
            try:
                btn.setMinimumSize(0, 0)
                btn.setMaximumSize(16777215, 16777215)
            except Exception:
                pass
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
            anim.finished.connect(lambda: self._cleanup_anims([anim]))
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
        # Also install on app if not already
        if app is not None and app is not target:
            app.installEventFilter(_animator_instance)
    # For widget case, ensure all existing buttons get filter via app-level already covers,
    # but also install per-button for direct press handling (some styles swallow)
    try:
        if hasattr(target, "findChildren"):
            for btn in target.findChildren(QPushButton):
                btn.installEventFilter(_animator_instance)
    except Exception:
        pass
    return _animator_instance


def install_button_animations_for_widget(widget):
    """
    Convenience: install animator for a specific widget subtree.
    Finds all QPushButtons under widget and ensures global animator will handle them.
    Uses eventFilter only (no clicked signal tampering) to avoid breaking existing connections.
    """
    global _animator_instance
    if _animator_instance is None:
        install_global_button_animation(widget)
    try:
        for btn in widget.findChildren(QPushButton):
            # Install per-button filter for reliability (global app filter already covers, but per-button ensures)
            btn.installEventFilter(_animator_instance)
    except Exception:
        pass
    return _animator_instance
