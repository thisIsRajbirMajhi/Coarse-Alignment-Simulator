# gui/__init__.py - Package marker + convenience re-exports
# Allows: `from gui import MainWindow` or `import gui`
# Canonical: `from gui.main_window import MainWindow` or `from gui.app import MainWindow`

try:
    from gui.main_window import MainWindow  # noqa: F401
except Exception:
    pass

__all__ = ["MainWindow"]
