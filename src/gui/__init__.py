# gui/__init__.py - Package marker + convenience re-exports
# Allows: `from src.gui import MainWindow` or `import src.gui`
# Canonical: `from src.gui.main_window import MainWindow` or `from src.gui.app import MainWindow`

try:
    from src.gui.main_window import MainWindow  # noqa: F401
except Exception:
    pass

__all__ = ["MainWindow"]
