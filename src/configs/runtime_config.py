# configs/runtime_config.py - Unified RuntimeConfig YAML loader (Spec FSOC&PAT:32)
from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass, field, asdict, is_dataclass
from pathlib import Path
from typing import Any

import yaml

from src.camera.config import CameraConfig, PIDConfig
from src.environment.config import EnvironmentConfig
from src.disturbance.core.config import DisturbanceConfig
from src.local_terminal.models import AutonomyConfig
from src.remote_terminal.config import RemoteScenarioConfig, make_default_scenario

# Optional logging config stub
@dataclass
class LoggingConfig:
    level: str = "INFO"
    log_dir: str = "outputs/logs"
    enable_frame_log: bool = False
    enable_run_log: bool = True

    def validate(self) -> "LoggingConfig":
        lvl = str(self.level).upper()
        if lvl not in ("DEBUG","INFO","WARNING","ERROR","CRITICAL"):
            lvl = "INFO"
        self.level = lvl
        self.log_dir = str(self.log_dir)
        self.enable_frame_log = bool(self.enable_frame_log)
        self.enable_run_log = bool(self.enable_run_log)
        return self

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "LoggingConfig":
        data = dict(data or {})
        obj = cls(
            level=str(data.get("level","INFO")),
            log_dir=str(data.get("log_dir","outputs/logs")),
            enable_frame_log=bool(data.get("enable_frame_log", False)),
            enable_run_log=bool(data.get("enable_run_log", True)),
        )
        return obj.validate()


@dataclass
class RuntimeConfig:
    """
    Unified config aggregating all subsystems per Spec FSOC&PAT:32.
    Groups: camera, pid, environment, disturbance, autonomy, remote, logging
    Provides: load_from_yaml, to_yaml, validate, to_dict, hash, CLI overrides.
    """
    camera: CameraConfig = field(default_factory=CameraConfig)
    pid: PIDConfig = field(default_factory=PIDConfig)
    environment: EnvironmentConfig = field(default_factory=EnvironmentConfig)
    disturbance: DisturbanceConfig = field(default_factory=DisturbanceConfig)
    autonomy: AutonomyConfig = field(default_factory=AutonomyConfig)
    remote: RemoteScenarioConfig = field(default_factory=make_default_scenario)
    logging: LoggingConfig = field(default_factory=LoggingConfig)

    # ---------- validation ----------
    def validate(self) -> "RuntimeConfig":
        self.camera = self.camera.validate()
        self.pid = self.pid.validate()
        self.environment = self.environment.validate()
        self.disturbance = self.disturbance.validate()
        try:
            self.autonomy = self.autonomy.validate()
        except Exception:
            self.autonomy = AutonomyConfig().validate()
        self.remote = self.remote.validate()
        self.logging = self.logging.validate()
        return self

    # ---------- dict ----------
    def to_dict(self) -> dict:
        import enum as _enum
        def _serial(v):
            if isinstance(v, _enum.Enum):
                return v.value
            if isinstance(v, (list, tuple)):
                return [_serial(x) for x in v]
            if isinstance(v, dict):
                return {k: _serial(x) for k,x in v.items()}
            return v
        def _asdict_sanitize(obj):
            d = obj.to_dict() if hasattr(obj,"to_dict") else asdict(obj)
            return _serial(d)
        return {
            "camera": _asdict_sanitize(self.camera),
            "pid": _asdict_sanitize(self.pid),
            "environment": _asdict_sanitize(self.environment),
            "disturbance": _asdict_sanitize(self.disturbance),
            "autonomy": _asdict_sanitize(self.autonomy),
            "remote": _serial({"formation": asdict(self.remote.formation), "terminals": [asdict(t) for t in self.remote.terminals], "single_beacon_mode": bool(getattr(self.remote,"single_beacon_mode", False))}),
            "logging": _asdict_sanitize(self.logging),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "RuntimeConfig":
        data = dict(data or {})
        def _pick(key, cfg_cls, default_factory):
            sub = data.get(key, None)
            if sub is None:
                return default_factory()
            if isinstance(sub, dict):
                try:
                    return cfg_cls.from_dict(sub)
                except Exception:
                    # fallback: filter fields
                    try:
                        from dataclasses import fields as _fields
                        allowed = {f.name for f in _fields(cfg_cls)}
                        filtered = {k:v for k,v in sub.items() if k in allowed}
                        return cfg_cls(**filtered).validate()
                    except Exception:
                        return default_factory()
            return default_factory()
        # remote special: formation shape enums etc
        remote = None
        if "remote" in data and isinstance(data["remote"], dict):
            try:
                remote = RemoteScenarioConfig.from_dict(data["remote"])
            except Exception:
                remote = make_default_scenario()
        else:
            remote = make_default_scenario()
        # logging
        log_cfg = LoggingConfig.from_dict(data.get("logging", {})) if isinstance(data.get("logging"), dict) else LoggingConfig()
        obj = cls(
            camera=_pick("camera", CameraConfig, CameraConfig),
            pid=_pick("pid", PIDConfig, PIDConfig),
            environment=_pick("environment", EnvironmentConfig, EnvironmentConfig),
            disturbance=_pick("disturbance", DisturbanceConfig, DisturbanceConfig),
            autonomy=_pick("autonomy", AutonomyConfig, AutonomyConfig),
            remote=remote,
            logging=log_cfg,
        )
        # support aliases: 'target','tracking','ai'
        # 'target' aliases to autonomy, 'tracking' to pid/camera
        if "target" in data and isinstance(data["target"], dict):
            try:
                obj.autonomy = AutonomyConfig.from_dict({**obj.autonomy.to_dict(), **data["target"]})
            except Exception:
                pass
        return obj.validate()

    # ---------- YAML ----------
    @classmethod
    def load_from_yaml(cls, path: str | Path) -> "RuntimeConfig":
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"Config file not found: {p}")
        text = p.read_text(encoding="utf-8")
        data = yaml.safe_load(text) or {}
        if not isinstance(data, dict):
            raise ValueError(f"YAML top-level must be mapping, got {type(data)}")
        return cls.from_dict(data)

    def to_yaml(self, path: str | Path) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        data = self.to_dict()
        with p.open("w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)

    # legacy aliases
    def save(self, path: str | Path) -> None:
        self.to_yaml(path)

    @classmethod
    def load(cls, path: str | Path) -> "RuntimeConfig":
        return cls.load_from_yaml(path)

    # ---------- hash ----------
    def hash(self) -> str:
        """Deterministic sha256 of canonical json."""
        canonical = json.dumps(self.to_dict(), sort_keys=True, default=str)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]

    def __hash__(self):  # type: ignore
        return hash(self.hash())

    # ---------- CLI overrides ----------
    def apply_cli_overrides(self, overrides: list[str] | dict[str, Any] | None) -> "RuntimeConfig":
        """
        Apply CLI overrides like ["camera.fov_deg_h=4.0", "pid.kp_pan=2.0"] or dict {"camera.fov_deg_h": 4.0}
        Supports dot-path into subgroups.
        """
        if not overrides:
            return self
        if isinstance(overrides, dict):
            items = [f"{k}={v}" for k,v in overrides.items()]
        else:
            items = list(overrides)
        for item in items:
            if not isinstance(item, str) or "=" not in item:
                continue
            key, val_s = item.split("=", 1)
            key = key.strip()
            val_s = val_s.strip()
            # parse value
            try:
                # try yaml load for typed value
                val = yaml.safe_load(val_s)
            except Exception:
                val = val_s
            self._set_dotted(key, val)
        return self.validate()

    def _set_dotted(self, dotted: str, value: Any) -> None:
        parts = dotted.split(".")
        if len(parts) < 2:
            return
        group = parts[0].lower()
        attr = ".".join(parts[1:])
        # handle nested like remote.single_beacon_mode or remote.formation.terminal_count
        target = None
        if group in ("camera",):
            target = self.camera
        elif group in ("pid","controller"):
            target = self.pid
        elif group in ("environment","env"):
            target = self.environment
        elif group in ("disturbance",):
            target = self.disturbance
        elif group in ("autonomy","local_terminal","local"):
            target = self.autonomy
        elif group in ("remote","scenario"):
            target = self.remote
        elif group in ("logging","log"):
            target = self.logging
        else:
            return
        # support nested dotted remainder
        cur = target
        sub_parts = attr.split(".")
        for p in sub_parts[:-1]:
            if hasattr(cur, p):
                cur = getattr(cur, p)
            else:
                return
        final = sub_parts[-1]
        if hasattr(cur, final):
            # coerce via original type if possible
            orig = getattr(cur, final)
            try:
                if isinstance(orig, bool):
                    if isinstance(value, str):
                        value = value.lower() in ("1","true","yes","on")
                    else:
                        value = bool(value)
                elif isinstance(orig, int) and not isinstance(orig, bool):
                    value = int(value)
                elif isinstance(orig, float):
                    value = float(value)
            except Exception:
                pass
            setattr(cur, final, value)

    # ---------- session integration ----------
    def apply_to_session(self, session) -> None:
        """Hot-reload into SimulationSession via its apply_* methods."""
        try:
            session.apply_camera_config(self.camera)
        except Exception:
            pass
        try:
            session.apply_controller_config(self.pid)
        except Exception:
            pass
        try:
            session.apply_environment_config(self.environment)
        except Exception:
            pass
        try:
            session.apply_disturbance_config(self.disturbance)
        except Exception:
            pass
        try:
            session.apply_local_terminal_config(self.autonomy)
        except Exception:
            pass
        try:
            session.apply_remote_config(self.remote)
        except Exception:
            pass

# Module-level helpers per spec
def load_config(path: str | Path, cli_overrides: list[str] | dict | None = None) -> RuntimeConfig:
    cfg = RuntimeConfig.load_from_yaml(path)
    if cli_overrides:
        cfg.apply_cli_overrides(cli_overrides)
    return cfg.validate()

def validate_config(cfg: RuntimeConfig | dict) -> RuntimeConfig:
    if isinstance(cfg, dict):
        return RuntimeConfig.from_dict(cfg)
    return cfg.validate()

def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="RuntimeConfig YAML loader")
    p.add_argument("--config", type=str, default="src/configs/default.yaml", help="Path to YAML config")
    p.add_argument("--set", dest="overrides", action="append", default=[], help="Override key=value (e.g. camera.fov_deg_h=6)")
    return p

def parse_cli_args(args: list[str] | None = None) -> RuntimeConfig:
    parser = build_arg_parser()
    ns, _ = parser.parse_known_args(args)
    cfg = RuntimeConfig()
    if ns.config:
        try:
            cfg = RuntimeConfig.load_from_yaml(ns.config)
        except FileNotFoundError:
            pass
    if ns.overrides:
        cfg.apply_cli_overrides(ns.overrides)
    return cfg.validate()
