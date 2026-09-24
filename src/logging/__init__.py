# logging/__init__.py — Shadow-safe wrapper around stdlib `logging`.
# This package is named `logging` per task spec, which normally shadows stdlib `logging`.
# To preserve `import logging` semantics for the whole repo, we re-export the
# stdlib `logging` API and extend `__path__` to include the stdlib logging package
# so that `import src.logging.handlers` etc. still resolve.
from __future__ import annotations

import sys
import sysconfig
import pathlib
import importlib.util
import importlib.machinery

# Resolve stdlib logging directory
_STDLIB_LOGGING_DIR: pathlib.Path | None = None
_STDLIB_LOGGING_FILE: pathlib.Path | None = None
try:
    stdlib_root = pathlib.Path(sysconfig.get_path("stdlib"))
    cand_dir = stdlib_root / "logging"
    cand_file = cand_dir / "__init__.py"
    if cand_dir.is_dir() and cand_file.is_file():
        _STDLIB_LOGGING_DIR = cand_dir
        _STDLIB_LOGGING_FILE = cand_file
    else:
        # Fallback via find_spec without local path
        import importlib.util as _ilu
        _saved_path = list(sys.path)
        try:
            # Remove repo root (which contains our logging/) to find stdlib spec
            repo_root = pathlib.Path(__file__).resolve().parent.parent
            repo_posix = repo_root.as_posix()
            sys.path = [p for p in sys.path if pathlib.Path(p).resolve().as_posix() != repo_posix] if repo_posix else sys.path
            spec = _ilu.find_spec("logging")
            if spec and spec.origin and "site-packages" not in spec.origin and spec.origin.endswith("__init__.py"):
                _STDLIB_LOGGING_FILE = pathlib.Path(spec.origin)
                _STDLIB_LOGGING_DIR = _STDLIB_LOGGING_FILE.parent
        finally:
            sys.path = _saved_path
except Exception:
    pass

# Extend __path__ so submodule imports like `logging.handlers` also search stdlib
try:
    _this_dir = pathlib.Path(__file__).resolve().parent
    _paths: list[str] = [str(_this_dir)]
    if _STDLIB_LOGGING_DIR is not None and _STDLIB_LOGGING_DIR.is_dir():
        _paths.append(str(_STDLIB_LOGGING_DIR))
    __path__ = _paths  # type: ignore
except Exception:
    pass

# Re-export stdlib logging API into this package namespace for transparency.
# We load the stdlib module from its file location under a private name, then
# copy its public attributes so that `import logging; logging.getLogger` works.
_STDLIB_MODULE = None
try:
    if _STDLIB_LOGGING_FILE is not None and _STDLIB_LOGGING_FILE.is_file():
        spec = importlib.util.spec_from_file_location("_stdlib_logging", str(_STDLIB_LOGGING_FILE),
                                                        submodule_search_locations=[str(_STDLIB_LOGGING_DIR)] if _STDLIB_LOGGING_DIR else None)
        if spec and spec.loader:
            mod = importlib.util.module_from_spec(spec)
            # Ensure `logging` package import machinery can resolve submodules
            sys.modules["_stdlib_logging"] = mod
            spec.loader.exec_module(mod)  # type: ignore
            _STDLIB_MODULE = mod
            # Copy attributes
            for _k in dir(mod):
                if _k.startswith("__") and _k not in ("__all__",):
                    continue
                try:
                    globals()[_k] = getattr(mod, _k)
                except Exception:
                    pass
            # Preserve __all__ if present
            if hasattr(mod, "__all__"):
                try:
                    globals()["__all__"] = list(getattr(mod, "__all__"))  # type: ignore
                except Exception:
                    pass
            # Also expose submodules already loaded via sys.modules under stdlib prefix?
            # sys.modules still has our package as `logging`; keep stdlib available as `_stdlib_logging`
        else:
            # Fallback: try direct import after path tweak
            raise FileNotFoundError(str(_STDLIB_LOGGING_FILE))
    else:
        raise FileNotFoundError("stdlib logging not found")
except Exception as _e:
    # If stdlib load failed, keep minimal shim; imports like `import logging; logging.getLogger`
    # would fail loudly — which is better than silent shadow. Try fallback import with temporary path removal.
    try:
        _saved = list(sys.path)
        repo_root2 = pathlib.Path(__file__).resolve().parent.parent
        repo_posix2 = repo_root2.as_posix()
        sys.path = [p for p in sys.path if pathlib.Path(p).resolve().as_posix() != repo_posix2]
        import importlib as _il
        _STDLIB_MODULE = _il.import_module("logging")
        for _k in dir(_STDLIB_MODULE):
            if _k.startswith("__") and _k not in ("__all__",):
                continue
            try:
                globals()[_k] = getattr(_STDLIB_MODULE, _k)
            except Exception:
                pass
    except Exception:
        pass
    finally:
        try:
            sys.path = _saved  # type: ignore
        except Exception:
            pass

# Re-export run_logger / frame_logger / schemas lazily (avoid circular import at package import time)
__all__ = list(globals().get("__all__", [])) + ["run_logger", "frame_logger", "schemas"]
