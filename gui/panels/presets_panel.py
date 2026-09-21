# gui/panels/presets_panel.py - Testing Presets Panel (collapsible per-preset cards).
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QCheckBox,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from gui.panels.base import BaseConfigPanel

log = logging.getLogger(__name__)


@dataclass
class PresetDefinition:
    id: str
    name: str
    category: str  # Baseline / Stress / Multi-target etc
    difficulty: str  # Easy / Medium / Hard
    description: str
    goal: str
    # Human-readable config summary (shown in card)
    configs: list[tuple[str, str]] = field(default_factory=list)
    # Expected results (shown in card)
    expected: list[tuple[str, str]] = field(default_factory=list)
    # Builder that returns validated config bundle for session apply
    # bundle keys: scenario, camera, pid, autonomy, disturbance, env (any may be None)
    bundle_builder: object = None  # callable -> dict


def _far_camera(fov_h: float = 4.0, fov_v: float | None = None, **kw):
    """Helper: camera parked far from scene centre (top-left) so SEARCH is required.
    start_* -90/90 clamp to world-bounds effective limit; scan starts at 0.
    """
    from camera.config import CameraConfig
    if fov_v is None:
        fov_v = fov_h * 0.75
    base = dict(fov_deg_h=float(fov_h), fov_deg_v=float(fov_v),
                use_custom_start=True, start_pan_deg=-90.0, start_tilt_deg=90.0,
                scan_start_index=0, **kw)
    return CameraConfig(**base).validate()


def _far_formation(**kw):
    """Helper: formation offset far from camera (bottom-right) to force raster search."""
    from remote_terminal.config import RemoteFormationConfig
    base = dict(start_offset_x_m=600.0, start_offset_y_m=600.0)
    base.update(kw)
    return RemoteFormationConfig(**base)


def _build_bundles():
    """Factory helpers for preset bundles — imported lazily to avoid circular."""
    from camera.config import CameraConfig, PIDConfig
    from disturbance.core.config import DisturbanceConfig
    from environment.config import EnvironmentConfig
    from local_terminal.models import AutonomyConfig
    from remote_terminal.config import (
        FormationShape,
        MotionProfile,
        RemoteFormationConfig,
        RemoteScenarioConfig,
        RemoteTerminalConfig,
    )

    def baseline_clean():
        return {
            "scenario": RemoteScenarioConfig(
                formation=_far_formation(
                    terminal_count=1, formation_shape=FormationShape.SINGLE,
                    motion_profile=MotionProfile.CONSTANT_VELOCITY,
                    terminal_spacing_m=100.0, speed_mps=5.0, heading_deg=0.0),
                terminals=[RemoteTerminalConfig(terminal_id="RT-001", optical_power_w=0.8, wavelength_nm=1550.0, spot_size_mrad=1.0)],
            ).validate(),
            "camera": _far_camera(fov_h=4.0, fov_v=3.0, max_pan_speed_deg_s=5.0, max_tilt_speed_deg_s=5.0),
            "pid": PIDConfig(kp_pan=1.5, ki_pan=0.1, kd_pan=0.25, kp_tilt=1.5, ki_tilt=0.1, kd_tilt=0.25, mode="AUTO").validate(),
            "autonomy": AutonomyConfig(candidate_min_snr_db=6.0, candidate_confirm_frames=2, p_rx_threshold_w=0.0, active_target_policy="priority", search_start_index=0).validate(),
            "disturbance": DisturbanceConfig(global_enabled=False).validate(),
            "env": EnvironmentConfig(seed=42, world_width=2000, world_height=2000).validate(),
        }

    def multi_target_line():
        return {
            "scenario": RemoteScenarioConfig(
                formation=_far_formation(
                    terminal_count=3, formation_shape=FormationShape.LINE,
                    motion_profile=MotionProfile.LINEAR, terminal_spacing_m=120.0, speed_mps=8.0, heading_deg=10.0),
                terminals=[
                    RemoteTerminalConfig(terminal_id="RT-001", optical_power_w=0.5),
                    RemoteTerminalConfig(terminal_id="RT-002", optical_power_w=0.8),
                    RemoteTerminalConfig(terminal_id="RT-003", optical_power_w=0.3),
                ],
            ).validate(),
            "camera": _far_camera(fov_h=4.0, max_pan_speed_deg_s=5.0),
            "pid": PIDConfig(mode="AUTO").validate(),
            "autonomy": AutonomyConfig(active_target_policy="priority", mission_priority=["RT-002", "RT-001", "RT-003"], search_start_index=0).validate(),
            "disturbance": DisturbanceConfig(global_enabled=False).validate(),
            "env": EnvironmentConfig(seed=7).validate(),
        }

    def low_snr_dim():
        return {
            "scenario": RemoteScenarioConfig(
                formation=_far_formation(terminal_count=1, formation_shape=FormationShape.SINGLE,
                                                motion_profile=MotionProfile.CONSTANT_VELOCITY, speed_mps=3.0),
                terminals=[RemoteTerminalConfig(terminal_id="RT-001", optical_power_w=0.15, wavelength_nm=1550.0, spot_size_mrad=0.8)],
            ).validate(),
            "camera": _far_camera(fov_h=3.0),
            "pid": PIDConfig(mode="AUTO").validate(),
            "autonomy": AutonomyConfig(candidate_min_snr_db=6.0, candidate_confirm_frames=2, p_rx_threshold_w=0.0002,
                                       coast_timeout_s=1.0, lost_timeout_s=0.5, lost_uncertainty_threshold_px=30.0, search_start_index=0).validate(),
            "disturbance": DisturbanceConfig(global_enabled=False).validate(),
            "env": EnvironmentConfig(seed=99).validate(),
        }

    def high_dynamics_agile():
        return {
            "scenario": RemoteScenarioConfig(
                formation=_far_formation(terminal_count=1, formation_shape=FormationShape.SINGLE,
                                                motion_profile=MotionProfile.CIRCULAR, speed_mps=45.0),
                terminals=[RemoteTerminalConfig(terminal_id="RT-001", optical_power_w=1.0, spot_size_mrad=1.2)],
            ).validate(),
            "camera": _far_camera(fov_h=6.0, fov_v=4.5, max_pan_speed_deg_s=10.0, max_tilt_speed_deg_s=10.0,
                                   max_pan_accel_deg_s2=60.0, max_tilt_accel_deg_s2=60.0),
            "pid": PIDConfig(kp_pan=3.0, ki_pan=0.3, kd_pan=0.45, kp_tilt=3.0, ki_tilt=0.3, kd_tilt=0.45, mode="AUTO").validate(),
            "autonomy": AutonomyConfig(kalman_process_noise_q=12.0, association_mahal_threshold=12.0, search_start_index=0).validate(),
            "disturbance": DisturbanceConfig(global_enabled=False).validate(),
            "env": EnvironmentConfig(seed=123).validate(),
        }

    def lost_and_reacq():
        return {
            "scenario": RemoteScenarioConfig(
                formation=_far_formation(terminal_count=2, formation_shape=FormationShape.LINE,
                                                terminal_spacing_m=200.0, motion_profile=MotionProfile.SINUSOIDAL, speed_mps=10.0),
                terminals=[
                    RemoteTerminalConfig(terminal_id="RT-001", optical_power_w=0.6),
                    RemoteTerminalConfig(terminal_id="RT-002", optical_power_w=0.9),
                ],
            ).validate(),
            "camera": _far_camera(),
            "pid": PIDConfig(mode="AUTO").validate(),
            "autonomy": AutonomyConfig(reacq_radii_px=[50, 100, 200, 400, 800], reacq_full_scan_enabled=True,
                                       lost_timeout_s=0.4, lost_uncertainty_threshold_px=25.0, search_start_index=0).validate(),
            "disturbance": DisturbanceConfig(global_enabled=False).validate(),
            "env": EnvironmentConfig(seed=202).validate(),
        }

    def severe_disturb():
        return {
            "scenario": RemoteScenarioConfig(
                formation=_far_formation(terminal_count=1, formation_shape=FormationShape.SINGLE,
                                                motion_profile=MotionProfile.RANDOM, speed_mps=6.0),
                terminals=[RemoteTerminalConfig(terminal_id="RT-001", optical_power_w=0.5, wavelength_nm=1550.0)],
            ).validate(),
            "camera": _far_camera(fov_h=4.0, max_pan_speed_deg_s=5.0),
            "pid": PIDConfig(mode="AUTO").validate(),
            "autonomy": AutonomyConfig(candidate_min_snr_db=6.0, search_start_index=0).validate(),
            "disturbance": DisturbanceConfig(
                global_enabled=True, atmospheric_preset="Clear", channel_severity=0.0,
                turbulence=0, vibration=4.0, camera_motion=3.0,
                camera_jitter=10.0, camera_jitter_enabled=True,
                platform_speed=10.0, platform_profile="Random",
                enable_gaussian=False, enable_salt_pepper=False, enable_poisson=False,
            ).validate(),
            "env": EnvironmentConfig(seed=555, haze_pct=0).validate(),
        }

    return {
        "baseline_clean": baseline_clean,
        "multi_target_line": multi_target_line,
        "low_snr_dim": low_snr_dim,
        "high_dynamics_agile": high_dynamics_agile,
        "lost_and_reacq": lost_and_reacq,
        "severe_disturb": severe_disturb,
    }


def get_preset_definitions() -> list[PresetDefinition]:
    bundles = _build_bundles()
    return [
        PresetDefinition(
            id="baseline_clean", name="Baseline — Clean Single Target", category="Baseline", difficulty="Easy",
            description="Single RT-001 far bottom-right vs camera top-left — forces 20-cell SEARCH → IDENTIFY→ASSOCIATE→TRACK (full pipeline).",
            goal="Verify full pipeline: SEARCH raster finds beam, TID 0.8W decoded, boresight associate ~10px, then <5px track. Tests SEARCH not immediate lock.",
            configs=[
                ("Remote", "1× SINGLE · 5 m/s · RT-001 0.8W 1550nm · offset 600,600 (far)"),
                ("Camera", "4.0°×3.0° · 5°/s · 640×480 · parked top-left (far)"),
                ("Autonomy", "SNR 6dB · confirm 2 · P_rx 0 · priority · SEARCH required"),
                ("PID", "Balanced (Kp1.5/Ki0.1/Kd0.25) AUTO"),
                ("Disturb", "OFF · Clear"),
                ("Env", "2000×2000 seed 42"),
            ],
            expected=[
                ("Acquisition", "< 1.0 s"),
                ("Tracking error", "< 5 px / <0.4 mrad"),
                ("Retention", "> 99%"),
                ("Reacq", "0 events expected"),
            ],
            bundle_builder=bundles["baseline_clean"],
        ),
        PresetDefinition(
            id="multi_target_line", name="Multi-Target — Line of 3", category="Multi-target", difficulty="Medium",
            description="Three terminals in LINE (120m) far bottom-right, camera top-left — forces full SEARCH before priority select. Tests selector does not steal lock.",
            goal="SEARCH finds 3, IDENTIFY decodes RT-002, ASSOCIATE boresight, TRACK stays on RT-002 even when RT-001 brighter/nearer.",
            configs=[
                ("Remote", "3× LINE 120m · 8 m/s · RT-001/002/003 · offset 600,600 (far)"),
                ("Camera", "4.0° · 5°/s · parked top-left (far)"),
                ("Autonomy", "Policy priority · order RT-002,001,003 · SEARCH required"),
                ("PID", "Balanced AUTO"),
                ("Disturb", "OFF"),
            ],
            expected=[
                ("Acquisition", "< 1.5 s on RT-002"),
                ("Lock steal", "0 — nearest≠brighter must not steal"),
                ("Tracking error", "< 6 px"),
            ],
            bundle_builder=bundles["multi_target_line"],
        ),
        PresetDefinition(
            id="low_snr_dim", name="Low SNR — Dim Beacon", category="Stress", difficulty="Medium",
            description="Dim 0.15W far bottom-right vs narrow 3.0° camera top-left — dim power stresses SNR gate; forces SEARCH then COAST→LOST→REACQ.",
            goal="Verify full pipeline: narrow SEARCH finds dim, IDENTIFY CRC, COAST on fade (cov grows), LOST 0.5s/30px, REACQ ladder TID-gated. No instability.",
            configs=[
                ("Remote", "1× SINGLE · RT-001 0.15W dim · offset 600,600 (far)"),
                ("Camera", "3.0° narrow · parked top-left (far)"),
                ("Autonomy", "SNR 6dB · P_rx 0.2mW · lost 0.5s/30px · narrow SEARCH"),
                ("Disturb", "OFF (clean)"),
            ],
            expected=[
                ("Acquisition", "< 2 s"),
                ("Coast events", "1–3 expected"),
                ("Lost → Reacq", "≤ 1 s after fade return"),
                ("Tracking error", "< 10 px outside fade"),
            ],
            bundle_builder=bundles["low_snr_dim"],
        ),
        PresetDefinition(
            id="high_dynamics_agile", name="High Dynamics — Agile + Circular", category="Stress", difficulty="Hard",
            description="Circular 45 m/s far vs wide 6° Agile camera far — Agile must SEARCH wider, then aggressive PID holds high rate without LOST.",
            goal="Verify SEARCH wide finds fast mover, then TRACK with Q12/Mahal12 holds <10px at 45 m/s, no LOST, PID not saturating.",
            configs=[
                ("Remote", "1× CIRCULAR · 45 m/s · RT-001 1.0W · offset 600,600 (far)"),
                ("Camera", "6.0°×4.5° · 10°/s Agile · parked top-left (far)"),
                ("Autonomy", "Q 12 · Mahal 12 · SEARCH wide"),
                ("PID", "Aggressive Kp3.0/Ki0.3/Kd0.45"),
            ],
            expected=[
                ("Acquisition", "< 0.8 s (wide FOV)"),
                ("Tracking error", "< 10 px"),
                ("Loss", "0 — loop holds at rate"),
            ],
            bundle_builder=bundles["high_dynamics_agile"],
        ),
        PresetDefinition(
            id="lost_and_reacq", name="Lost & Reacquire — 2 Targets", category="Recovery", difficulty="Medium",
            description="Two terminals sinusoidal far vs camera far — forces SEARCH, then TRACK, then LOST→REACQ ladder. Wrong TID must not steal.",
            goal="Verify full pipeline: SEARCH→TRACK, then LOST 0.4s/25px → REACQ 50→800 TID-gated. RT-001 must not steal RT-002.",
            configs=[
                ("Remote", "2× LINE 200m · sinusoidal 10 m/s · offset 600,600 (far)"),
                ("Camera", "4.0° · parked top-left (far) · SEARCH required"),
                ("Autonomy", "Reacq 50→800 + full-scan · lost 0.4s/25px"),
            ],
            expected=[
                ("LOST", "visible in telemetry"),
                ("Reacq", "< 1 s (≤1.0s PDF Sr19) · correct TID only"),
                ("Steal", "0"),
            ],
            bundle_builder=bundles["lost_and_reacq"],
        ),
        PresetDefinition(
            id="severe_disturb", name="Severe — Shake + Platform", category="Stress", difficulty="Hard",
            description="Random 6 m/s far vs camera far — pose jitter 10px + platform 10px forces repeated SEARCH→TRACK→COAST→REACQ; no heavy blur (real-time).",
            goal="Verify SEARCH finds despite shake, TRACK degrades but holds, LOST→REACQ recovers; tests geometric robustness full pipeline.",
            configs=[
                ("Remote", "1× RANDOM 6 m/s · offset 600,600 (far)"),
                ("Camera", "4.0° · parked top-left (far) · SEARCH required"),
                ("Disturb", "Shake 10px · Random 10px · vib4 · drift3 · Clear"),
                ("Env", "Clear seed 555"),
            ],
            expected=[
                ("Acquisition", "< 2 s (may need second scan)"),
                ("Tracking error", "5–15 px (degraded)"),
                ("Retention", "> 85%"),
                ("Stability", "PID no windup/crash"),
            ],
            bundle_builder=bundles["severe_disturb"],
        ),
    ]


def _apply_to_session(session, key: str, cfg) -> None:
    """Dispatch apply to Session (GUI) or HeadlessSimulation (no apply_* helpers)."""
    # GUI SimulationSession has apply_*; HeadlessSimulation is dict-like.
    mapper = {
        "scenario": ("apply_remote_config", "scenario_config"),
        "camera": ("apply_camera_config", "camera_config"),
        "pid": ("apply_controller_config", "pid_config"),
        "autonomy": ("apply_local_terminal_config", "autonomy_config"),
        "disturbance": ("apply_disturbance_config", "disturbance_config"),
        "env": ("apply_environment_config", "env_config"),
    }
    meth, attr = mapper[key]
    if hasattr(session, meth):
        getattr(session, meth)(cfg)
    else:
        setattr(session, attr, cfg.validate() if hasattr(cfg, "validate") else cfg)
        # Headless: re-validate dependents lazily on next build/step
        try:
            if key == "scenario":
                from local_terminal import SignatureRegistry
                if hasattr(session, "supervisor"):
                    session.supervisor.set_registry(SignatureRegistry.from_scenario(cfg))
        except Exception:
            pass


def apply_preset_to_session(session, preset_id: str) -> dict:
    """Apply preset bundle to a SimulationSession or HeadlessSimulation session (headless + GUI)."""
    defs = {p.id: p for p in get_preset_definitions()}
    if preset_id not in defs:
        raise ValueError(f"Unknown preset {preset_id!r}. Known: {list(defs)}")
    bundle = defs[preset_id].bundle_builder()
    applied = {}
    if bundle.get("scenario") is not None:
        _apply_to_session(session, "scenario", bundle["scenario"])
        applied["scenario"] = bundle["scenario"].formation.terminal_count
    if bundle.get("camera") is not None:
        _apply_to_session(session, "camera", bundle["camera"])
        applied["camera"] = bundle["camera"].fov_deg_h
    if bundle.get("pid") is not None:
        _apply_to_session(session, "pid", bundle["pid"])
        applied["pid"] = bundle["pid"].mode
    if bundle.get("autonomy") is not None:
        _apply_to_session(session, "autonomy", bundle["autonomy"])
        applied["autonomy"] = bundle["autonomy"].candidate_min_snr_db
    if bundle.get("disturbance") is not None:
        _apply_to_session(session, "disturbance", bundle["disturbance"])
        applied["disturbance"] = bundle["disturbance"].atmospheric_preset
    if bundle.get("env") is not None:
        _apply_to_session(session, "env", bundle["env"])
        applied["env"] = bundle["env"].seed
    return applied


class PresetsPanel(BaseConfigPanel):
    """Testing Presets — 6 collapsible cards, each shows configs / goal / expected."""

    applyRequested = pyqtSignal(str)  # preset id

    def __init__(self, parent=None):
        super().__init__(parent)
        self._presets = get_preset_definitions()
        self._expanded: set[str] = set()
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        title = QLabel("TEST PRESETS")
        title.setStyleSheet("font-size:15px; font-weight:700;")
        hdr = QHBoxLayout()
        hdr.addWidget(title)
        hdr.addStretch(1)
        hint = QLabel("6 scenarios — click to expand, Apply to load")
        hint.setStyleSheet("color:#64748b; font-size:11px;")
        hdr.addWidget(hint)
        root.addLayout(hdr)

        sub = QLabel("Each preset is one config bundle (remote·camera·PID·autonomy·disturbance·env) with goal & pass criteria.")
        sub.setStyleSheet("color:#8F9CAB; font-size:11px;")
        sub.setWordWrap(True)
        root.addWidget(sub)

        for preset in self._presets:
            card = self._make_card(preset)
            root.addWidget(card)

        root.addStretch(1)

    def _make_card(self, preset: PresetDefinition) -> QFrame:
        card = QFrame()
        card.setObjectName("presetCard")
        card.setStyleSheet("QFrame#presetCard { background:#ffffff; border:1px solid #e5e7eb; border-radius:8px; }")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(8)

        # Header row: expand toggle + category/difficulty + Apply
        head = QHBoxLayout()
        head.setSpacing(8)
        btn_expand = QPushButton(f"▸  {preset.name}")
        btn_expand.setCheckable(True)
        btn_expand.setMinimumHeight(32)
        btn_expand.setStyleSheet(
            "QPushButton { text-align:left; background:transparent; border:none; color:#111827; font-weight:700; font-size:12px; }"
            "QPushButton:checked { color:#1e40af; }"
        )
        cat = QLabel(f"{preset.category} · {preset.difficulty}")
        cat.setStyleSheet("color:#6b7280; font-size:10px; background:#f3f4f6; border-radius:8px; padding:2px 8px;")
        cat.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        btn_apply = QPushButton("Apply")
        btn_apply.setMinimumHeight(28)
        btn_apply.setToolTip(f"Load preset '{preset.name}' into the session")
        btn_apply.setStyleSheet("QPushButton { background:#111827; color:white; font-weight:700; border-radius:6px; padding:4px 12px; } QPushButton:hover { background:#1f2937; }")
        btn_apply.clicked.connect(lambda _, pid=preset.id: self.applyRequested.emit(pid))
        head.addWidget(btn_expand, 1)
        head.addWidget(cat)
        head.addWidget(btn_apply)
        lay.addLayout(head)

        # Collapsible body
        body = QWidget()
        body.setVisible(False)
        blay = QVBoxLayout(body)
        blay.setContentsMargins(4, 4, 4, 4)
        blay.setSpacing(8)

        desc = QLabel(preset.description)
        desc.setWordWrap(True)
        desc.setStyleSheet("color:#374151; font-size:11px;")
        blay.addWidget(desc)

        # Goal
        goal_box, goal_grid = self._make_group("END GOAL")
        goal_lbl = QLabel(preset.goal)
        goal_lbl.setWordWrap(True)
        goal_lbl.setStyleSheet("color:#1e3a8a; font-size:11px; font-weight:600;")
        goal_grid.addWidget(goal_lbl, 0, 0)
        blay.addWidget(goal_box)

        # Configs table
        cfg_box, cfg_grid = self._make_group("CONFIGURATIONS")
        for i, (k, v) in enumerate(preset.configs):
            cfg_grid.addWidget(self._label(k), i, 0)
            val = QLabel(v)
            val.setStyleSheet("color:#111827; font-size:11px; font-family:'Consolas','Courier New',monospace;")
            val.setWordWrap(True)
            cfg_grid.addWidget(val, i, 1)
        blay.addWidget(cfg_box)

        # Expected results
        res_box, res_grid = self._make_group("EXPECTED RESULTS")
        for i, (k, v) in enumerate(preset.expected):
            res_grid.addWidget(self._label(k), i, 0)
            val = QLabel(v)
            val.setStyleSheet("color:#065f46; font-size:11px; font-weight:700;")
            res_grid.addWidget(val, i, 1)
        blay.addWidget(res_box)

        # Second Apply at bottom for long cards
        bottom_apply = QPushButton("Apply this preset")
        bottom_apply.setMinimumHeight(32)
        bottom_apply.setStyleSheet("QPushButton { background:#111827; color:white; font-weight:700; border-radius:6px; } QPushButton:hover { background:#1f2937; }")
        bottom_apply.clicked.connect(lambda _, pid=preset.id: self.applyRequested.emit(pid))
        blay.addWidget(bottom_apply)

        lay.addWidget(body)

        def _toggle(checked: bool, _body=body, _btn=btn_expand, _name=preset.name):
            _body.setVisible(checked)
            _btn.setText(("▾  " if checked else "▸  ") + _name)
            if checked:
                self._expanded.add(preset.id)
            else:
                self._expanded.discard(preset.id)
        btn_expand.toggled.connect(_toggle)

        # Keep refs for tests
        card._body = body
        card._expand = btn_expand
        card._apply = btn_apply
        return card

    # Back-compat helpers for set_config/collect if panel ever needs to be treated as config panel
    def collect_config(self):
        return None

    def set_config(self, cfg, emit: bool = False):
        pass


__all__ = ["PresetsPanel", "PresetDefinition", "get_preset_definitions", "apply_preset_to_session"]
