# gui/simulation/__init__.py - Tick & rendering delegation
# Canonical tick lives in gui/mixins/tick_mixin.py & rendering_mixin.py,
# this package groups simulation helpers and photometry if extracted to widgets.

from gui.mixins.tick_mixin import TickMixin  # noqa: F401
from gui.mixins.rendering_mixin import RenderingMixin  # noqa: F401
from gui.mixins.stats_mixin import StatsMixin  # noqa: F401

__all__ = ["TickMixin", "RenderingMixin", "StatsMixin"]
