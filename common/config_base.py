# common/config_base.py - Single source for Config validation pattern — eliminates 11× duplication

from __future__ import annotations

from dataclasses import asdict, fields, is_dataclass
from typing import Any, ClassVar

import numpy as np

def clip_field(value: Any, lo: float, hi: float) -> Any:
    """
    Clip single value to [lo, hi] preserving int vs float.
    - If value is int (and not bool), returns int
    - Otherwise returns same type as value (float)
    """
    try:
        if isinstance(value, bool):
            return bool(np.clip(int(value), lo, hi))
        if isinstance(value, (np.integer,)):
            return int(np.clip(int(value), lo, hi))
        if isinstance(value, (np.floating,)):
            return float(np.clip(float(value), lo, hi))
        is_int = isinstance(value, int) and not isinstance(value, bool)
        clipped = np.clip(value, lo, hi)
        if is_int:
            return int(clipped)
        if isinstance(value, float):
            return float(clipped)
        # fallback: try to preserve original type, but avoid bool truncation
        try:
            return type(value)(clipped)  # type: ignore
        except Exception:
            return int(clipped) if is_int else float(clipped)
    except Exception:
        return value

class BaseValidatedConfig:
    """
    Mixin for validated dataclass configs.

    Subclass should:
      - be a @dataclass
      - define class var LIMITS: dict[str, tuple] or override validate() to pass module LIMITS
      - define DEFAULTS dict at module level for from_dict filtering (optional)
    Provides:
      - validate(): clips every field found in LIMITS
      - to_dict(): asdict(self)
      - from_dict(cls, data): merges DEFAULTS + known fields then validate()
    """

    # Subclasses may override
    LIMITS: ClassVar[dict[str, tuple[float, float]]] = {}
    DEFAULTS: ClassVar[dict[str, Any]] = {}

    def validate(self) -> "BaseValidatedConfig":  # type: ignore[override]
        # Resolve LIMITS: prefer instance/class LIMITS, else empty
        limits = getattr(self.__class__, "LIMITS", {}) or getattr(self, "LIMITS", {})
        # Also allow module-level LIMITS via subclass override that imports
        # If subclass defines validate() that passes explicit limits, this is bypassed
        if limits:
            for fname, (lo, hi) in limits.items():
                if hasattr(self, fname):
                    try:
                        val = getattr(self, fname)
                        setattr(self, fname, clip_field(val, lo, hi))
                    except Exception:
                        pass
        return self  # type: ignore

    def to_dict(self) -> dict:
        if not is_dataclass(self):
            return dict(self.__dict__)
        return asdict(self)  # type: ignore

    @classmethod
    def from_dict(cls, data: dict) -> "BaseValidatedConfig":
        # Filter to known dataclass fields + DEFAULTS keys
        try:
            field_names = {f.name for f in fields(cls)}  # type: ignore
        except Exception:
            field_names = set(getattr(cls, "DEFAULTS", {}).keys())
        # Merge defaults
        defaults = getattr(cls, "DEFAULTS", {}) or {}
        # Also try module DEFAULTS import via class var
        if not defaults:
            # fallback to empty — caller may have module-level DEFAULTS
            defaults = {}
        known = {k: v for k, v in data.items() if k in field_names}
        merged = {**defaults, **known}
        # Only pass fields that are declared
        filtered = {k: v for k, v in merged.items() if k in field_names}
        obj = cls(**filtered)  # type: ignore
        return obj.validate()  # type: ignore