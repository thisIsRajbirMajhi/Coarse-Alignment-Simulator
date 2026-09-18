"""Optical Propagation Channel (Disturbance Medium).

Authoritative data flow per DisturbanceModel.txt::

    Remote Terminal → Ideal Optical Beam → Propagation Channel →
    Received Optical Signal → Local Terminal/PTZ Camera → Image Formation →
    Sensor Disturbance → Observed Frame → Detection/Centroid → Tracking

The channel modifies the *beam state* before the camera receives it. It must
not directly modify tracker output. Image-space helpers (blur/contrast) are a
rendering of the received optical state, not the channel itself.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from enum import Enum

import numpy as np

from common.rng import get_rng


class AtmosphericCondition(str, Enum):
    """Mandatory atmospheric conditions from the problem statement."""

    CLEAR = "Clear"
    HAZE = "Haze"
    FOG = "Fog"
    RAIN = "Rain"
    LOW_LIGHT = "Low light"

    @classmethod
    def normalize(cls, value: str) -> "AtmosphericCondition":
        low = str(value).strip().lower().replace("-", " ").replace("_", " ")
        mapping = {
            "clear": cls.CLEAR,
            "haze": cls.HAZE,
            "fog": cls.FOG,
            "rain": cls.RAIN,
            "low light": cls.LOW_LIGHT,
            "lowlight": cls.LOW_LIGHT,
            "low": cls.LOW_LIGHT,
            "user defined": cls.CLEAR,
            "userdefined": cls.CLEAR,
            "custom": cls.CLEAR,
        }
        return mapping.get(low, cls.CLEAR)


class AttenuationModel(str, Enum):
    FIXED = "Fixed"
    DISTANCE_BASED = "Distance Based"
    ATMOSPHERIC = "Atmospheric"
    CUSTOM = "Custom"


# Base (severity=1) channel losses per atmospheric condition.
# attenuation: fraction of emitted intensity that survives (Beer-Lambert style).
# contrast/brightness/visibility: 1.0 = ideal, lower = degraded.
_CHANNEL_BASE: dict[str, dict] = {
    "Clear": {"attenuation": 1.0, "contrast": 1.00, "brightness": 1.00, "visibility": 1.00,
              "spread": 1.00, "wander": 0.0, "scintillation": 0.0},
    "Haze": {"attenuation": 0.82, "contrast": 0.85, "brightness": 0.90, "visibility": 0.80,
             "spread": 1.12, "wander": 0.60, "scintillation": 0.08},
    "Fog": {"attenuation": 0.45, "contrast": 0.55, "brightness": 0.72, "visibility": 0.38,
            "spread": 1.45, "wander": 1.10, "scintillation": 0.16},
    "Rain": {"attenuation": 0.62, "contrast": 0.72, "brightness": 0.82, "visibility": 0.60,
             "spread": 1.25, "wander": 0.90, "scintillation": 0.14},
    "Low light": {"attenuation": 0.55, "contrast": 0.68, "brightness": 0.45, "visibility": 0.55,
                  "spread": 1.08, "wander": 0.40, "scintillation": 0.05},
}


@dataclass
class AttenuationConfig:
    enabled: bool = True
    strength: float = 1.0  # 0..1 extra user scaling on top of atmospheric loss
    model: str = AttenuationModel.ATMOSPHERIC.value


@dataclass
class ChannelState:
    """Centralized per-frame channel state — deterministic and testable."""

    enabled: bool = True
    atmosphericCondition: str = AtmosphericCondition.CLEAR.value
    severity: float = 1.0  # 0..1 (0 = ideal regardless of condition)
    attenuation: float = 1.0  # surviving fraction this frame
    turbulence: float = 0.0
    beamWander: tuple[float, float] = (0.0, 0.0)  # px offset (x, y)
    beamSpread: float = 1.0  # spot-size multiplier
    intensityFactor: float = 1.0
    contrastFactor: float = 1.0
    brightnessFactor: float = 1.0
    visibilityFactor: float = 1.0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class OpticalBeamState:
    """Ideal beam emitted by the Remote Terminal (before the channel)."""

    emittedIntensity: float = 1.0  # 0..~1.5 incl. temporal modulation
    position: tuple[float, float] = (0.0, 0.0)  # world px (geometric)
    direction: tuple[float, float] = (0.0, 0.0)  # az/el deg
    spotSize: float = 9.0  # px diameter of ideal patch
    wavelength_nm: float = 1550.0
    power_w: float = 1.0


@dataclass
class ReceivedOpticalState:
    """Degraded beam after the Propagation Channel (what the camera sees)."""

    intensity: float = 1.0
    position: tuple[float, float] = (0.0, 0.0)  # geometric + wander
    direction: tuple[float, float] = (0.0, 0.0)  # observed direction
    spotSize: float = 9.0  # after spreading
    intensityFactor: float = 1.0
    contrastFactor: float = 1.0
    brightnessFactor: float = 1.0
    visibilityFactor: float = 1.0
    channel: ChannelState = field(default_factory=ChannelState)


@dataclass
class ChannelWanderState:
    """Temporal OU state for beam wander + intensity fluctuation."""

    wx: float = 0.0
    wy: float = 0.0
    log_intensity: float = 0.0

    def clear(self) -> None:
        self.wx = 0.0
        self.wy = 0.0
        self.log_intensity = 0.0


class PropagationChannel:
    """Transforms ideal beam state into degraded received optical state.

    Deterministic given (config, dt, rng). All randomness flows through the
    provided ``rng``; temporal correlation uses OU processes keyed on dt.
    """

    WANDER_TAU = 0.11  # s — frozen-flow tilt decorrelation (matches turbulence)
    SCINT_TAU = 0.09  # s — intensity fluctuation decorrelation

    def __init__(
        self,
        atmospheric_condition: str = "Clear",
        severity: float = 1.0,
        attenuation: AttenuationConfig | None = None,
        turbulence: float = 0.0,
        beam_wander: float = 1.0,  # user gain 0..2 (1 = nominal)
        beam_spread: float = 1.0,  # user gain 0..2
        intensity_fluctuation: float = 1.0,  # user gain 0..2
        enabled: bool = True,
    ):
        self.atmospheric_condition = AtmosphericCondition.normalize(atmospheric_condition).value
        self.severity = float(np.clip(severity, 0.0, 1.0))
        self.attenuation_cfg = attenuation or AttenuationConfig()
        self.turbulence = float(np.clip(turbulence, 0.0, 10.0))
        self.beam_wander_gain = float(np.clip(beam_wander, 0.0, 2.0))
        self.beam_spread_gain = float(np.clip(beam_spread, 0.0, 2.0))
        self.intensity_fluct_gain = float(np.clip(intensity_fluctuation, 0.0, 2.0))
        self.enabled = bool(enabled)
        self.state = ChannelState()
        self.wander_state = ChannelWanderState()
        self._sync_state_baseline()

    # ------------------------------------------------------------------
    def _base(self) -> dict:
        return dict(_CHANNEL_BASE.get(self.atmospheric_condition, _CHANNEL_BASE["Clear"]))

    def _sync_state_baseline(self) -> None:
        base = self._base()
        sev = self.severity
        att = base["attenuation"]
        # severity interpolates between ideal (1.0) and base loss
        att = 1.0 - (1.0 - att) * sev
        if self.attenuation_cfg.enabled:
            att *= float(np.clip(self.attenuation_cfg.strength, 0.0, 1.0))
        else:
            att = 1.0
        self.state.enabled = self.enabled
        self.state.atmosphericCondition = self.atmospheric_condition
        self.state.severity = sev
        self.state.attenuation = float(np.clip(att, 0.0, 1.0))
        self.state.turbulence = float(self.turbulence)
        self.state.contrastFactor = float(np.clip(1.0 - (1.0 - base["contrast"]) * sev, 0.0, 1.0))
        self.state.brightnessFactor = float(np.clip(1.0 - (1.0 - base["brightness"]) * sev, 0.0, 1.0))
        self.state.visibilityFactor = float(np.clip(1.0 - (1.0 - base["visibility"]) * sev, 0.0, 1.0))
        self.state.intensityFactor = float(self.state.attenuation)
        spread = 1.0 + (base["spread"] - 1.0) * sev * self.beam_spread_gain
        self.state.beamSpread = float(max(1.0, spread))

    def configure(
        self,
        atmospheric_condition: str | None = None,
        severity: float | None = None,
        attenuation: AttenuationConfig | None = None,
        turbulence: float | None = None,
        beam_wander: float | None = None,
        beam_spread: float | None = None,
        intensity_fluctuation: float | None = None,
        enabled: bool | None = None,
    ) -> None:
        if atmospheric_condition is not None:
            self.atmospheric_condition = AtmosphericCondition.normalize(atmospheric_condition).value
        if severity is not None:
            self.severity = float(np.clip(severity, 0.0, 1.0))
        if attenuation is not None:
            self.attenuation_cfg = attenuation
        if turbulence is not None:
            self.turbulence = float(np.clip(turbulence, 0.0, 10.0))
        if beam_wander is not None:
            self.beam_wander_gain = float(np.clip(beam_wander, 0.0, 2.0))
        if beam_spread is not None:
            self.beam_spread_gain = float(np.clip(beam_spread, 0.0, 2.0))
        if intensity_fluctuation is not None:
            self.intensity_fluct_gain = float(np.clip(intensity_fluctuation, 0.0, 2.0))
        if enabled is not None:
            self.enabled = bool(enabled)
        self._sync_state_baseline()

    # ------------------------------------------------------------------
    def compute_attenuation(
        self,
        emitted_intensity: float,
        distance_m: float | None = None,
        wavelength_nm: float = 1550.0,
    ) -> float:
        """receivedIntensity = emittedIntensity × attenuationFactor."""
        if not self.enabled or not self.attenuation_cfg.enabled:
            return float(emitted_intensity)
        model = str(self.attenuation_cfg.model)
        factor = float(self.state.attenuation)
        if model == AttenuationModel.DISTANCE_BASED.value and distance_m is not None:
            # Beer-Lambert: exp(-beta * d); beta from current attenuation at 1 km ref
            beta = -math.log(max(1e-6, factor)) / 1000.0
            factor = math.exp(-beta * max(0.0, float(distance_m)))
            factor *= float(np.clip(self.attenuation_cfg.strength, 0.0, 1.0))
        elif model == AttenuationModel.FIXED.value:
            factor = float(np.clip(self.attenuation_cfg.strength, 0.0, 1.0))
        elif model == AttenuationModel.CUSTOM.value:
            factor = float(np.clip(self.attenuation_cfg.strength, 0.0, 1.0)) * factor
        return float(emitted_intensity) * float(np.clip(factor, 0.0, 1.0))

    def _step_wander(self, dt: float, rng: np.random.Generator, base_wander: float) -> tuple[float, float]:
        dt = float(np.clip(dt, 0.005, 0.08))
        alpha = math.exp(-dt / self.WANDER_TAU)
        scale = base_wander * math.sqrt(max(0.0, 1 - alpha * alpha))
        scale *= self.beam_wander_gain
        # turbulence broadens wander: +15% per turbulence unit up to 2.5x
        scale *= 1.0 + min(1.5, 0.15 * self.turbulence)
        self.wander_state.wx = self.wander_state.wx * alpha + float(rng.normal(0, 1)) * scale
        self.wander_state.wy = self.wander_state.wy * alpha + float(rng.normal(0, 1)) * scale
        max_w = 3.0 + 1.8 * self.turbulence + base_wander * 2.0
        return (
            float(np.clip(self.wander_state.wx, -max_w, max_w)),
            float(np.clip(self.wander_state.wy, -max_w, max_w)),
        )

    def _step_scintillation(self, dt: float, rng: np.random.Generator, base_scint: float) -> float:
        dt = float(np.clip(dt, 0.005, 0.08))
        sigma = (base_scint + 0.03 * self.turbulence) * self.intensity_fluct_gain * self.severity
        if sigma <= 1e-4:
            return 1.0
        alpha = math.exp(-dt / self.SCINT_TAU)
        self.wander_state.log_intensity = (
            self.wander_state.log_intensity * alpha
            + float(rng.normal(-sigma * sigma * (1 - alpha), sigma * math.sqrt(max(0.0, 1 - alpha * alpha))))
        )
        return float(np.clip(math.exp(self.wander_state.log_intensity), 0.45, 1.9))

    # ------------------------------------------------------------------
    def propagate_beam(
        self,
        beam: OpticalBeamState,
        dt: float = 1.0 / 30.0,
        rng: np.random.Generator | None = None,
        distance_m: float | None = None,
    ) -> ReceivedOpticalState:
        """Ideal beam → degraded received optical state."""
        _rng = get_rng(rng)
        self._sync_state_baseline()
        if not self.enabled or self.severity <= 1e-9:
            steady = ChannelState(
                enabled=self.enabled,
                atmosphericCondition=self.atmospheric_condition,
                severity=self.severity,
                attenuation=1.0 if not self.attenuation_cfg.enabled else float(self.state.attenuation),
                turbulence=self.turbulence,
                beamWander=(0.0, 0.0),
                beamSpread=1.0,
                intensityFactor=1.0,
                contrastFactor=1.0,
                brightnessFactor=1.0,
                visibilityFactor=1.0,
            )
            self.state = steady
            att = self.compute_attenuation(beam.emittedIntensity, distance_m, beam.wavelength_nm)
            return ReceivedOpticalState(
                intensity=float(att),
                position=tuple(beam.position),
                direction=tuple(beam.direction),
                spotSize=float(beam.spotSize),
                intensityFactor=float(att / max(1e-6, beam.emittedIntensity)) if beam.emittedIntensity > 1e-9 else 1.0,
                contrastFactor=1.0, brightnessFactor=1.0, visibilityFactor=1.0,
                channel=ChannelState(**asdict(steady)),
            )
        base = self._base()
        wx, wy = self._step_wander(dt, _rng, float(base["wander"]) * self.severity)
        scint = self._step_scintillation(dt, _rng, float(base["scintillation"]))
        att_intensity = self.compute_attenuation(beam.emittedIntensity, distance_m, beam.wavelength_nm)
        intensity = float(att_intensity * scint)
        # observedAngle = geometricAngle + channelBeamWander (px-mapped here)
        obs_pos = (float(beam.position[0] + wx), float(beam.position[1] + wy))
        # direction wander in deg: 1 px ≈ pixel scale — keep small angular nudge
        obs_dir = (float(beam.direction[0] + wx * 0.002), float(beam.direction[1] + wy * 0.002))
        spot = float(beam.spotSize * self.state.beamSpread)
        intensity_factor = float(intensity / max(1e-6, beam.emittedIntensity)) if beam.emittedIntensity > 1e-9 else 1.0
        self.state.beamWander = (float(wx), float(wy))
        self.state.intensityFactor = float(np.clip(intensity_factor, 0.0, 2.0))
        self.state.attenuation = float(np.clip(att_intensity / max(1e-6, beam.emittedIntensity), 0.0, 1.0)) if beam.emittedIntensity > 1e-9 else 1.0
        return ReceivedOpticalState(
            intensity=float(np.clip(intensity, 0.0, 3.0)),
            position=obs_pos,
            direction=obs_dir,
            spotSize=float(np.clip(spot, 1.0, 90.0)),
            intensityFactor=self.state.intensityFactor,
            contrastFactor=self.state.contrastFactor,
            brightnessFactor=self.state.brightnessFactor,
            visibilityFactor=self.state.visibilityFactor,
            channel=ChannelState(**asdict(self.state)),
        )

    def apply_to_patch(self, patch: np.ndarray, received: ReceivedOpticalState) -> np.ndarray:
        """Render received-state intensity/spread onto an ideal beacon patch."""
        import cv2

        if patch is None or patch.size == 0:
            return patch
        out = patch.astype(np.float32)
        gain = float(np.clip(received.intensityFactor, 0.0, 2.0))
        # visibility further dims the halo (beacon visibility degradation)
        gain *= float(np.clip(0.35 + 0.65 * received.visibilityFactor, 0.0, 1.0))
        out *= gain
        spread = float(received.spotSize) / 9.0
        if spread > 1.08:
            sigma = float(np.clip((spread - 1.0) * 1.6, 0.3, 3.5))
            k = int(np.clip(round(sigma * 3) * 2 + 1, 3, 11))
            out = cv2.GaussianBlur(out, (k, k), sigmaX=sigma)
            # energy conservation: spreading dims the peak
            out *= float(np.clip(1.0 / (0.55 + 0.45 * spread), 0.3, 1.0))
        return np.clip(out, 0, 255).astype(patch.dtype)

    def telemetry(self) -> dict:
        d = self.state.to_dict()
        d["attenuationModel"] = self.attenuation_cfg.model
        d["attenuationStrength"] = self.attenuation_cfg.strength
        return d

    def reset(self) -> None:
        self.wander_state.clear()
        self._sync_state_baseline()
        self.state.beamWander = (0.0, 0.0)
        self.state.intensityFactor = self.state.attenuation


__all__ = [
    "AtmosphericCondition", "AttenuationConfig", "AttenuationModel",
    "ChannelState", "ChannelWanderState", "OpticalBeamState",
    "PropagationChannel", "ReceivedOpticalState",
]
