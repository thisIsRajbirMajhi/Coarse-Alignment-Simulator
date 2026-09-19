"""Optical-owned disturbance orchestration.

Order per DisturbanceModel.txt §13::

    Ideal Optical Signal → Propagation Channel (beam-state) →
    Received Optical Signal → Camera → Image Formation → Sensor Effects
"""

from __future__ import annotations

import numpy as np

from disturbance.environment.atmospheric import apply_atmospheric_disturbance
from disturbance.optical.channel import (
    AttenuationConfig,
    OpticalBeamState,
    PropagationChannel,
    ReceivedOpticalState,
)
from disturbance.optical.turbulence import apply_turbulence
from disturbance.core.state import TurbulenceState


def _channel_from_config(config) -> PropagationChannel:
    try:
        if hasattr(config, "propagation_channel_config"):
            return config.propagation_channel_config()
    except Exception:
        pass
    # Fallback: build from legacy fields only.
    return PropagationChannel(
        atmospheric_condition=str(getattr(config, "atmospheric_preset", "Clear")),
        severity=float(getattr(config, "channel_severity", 1.0)),
        attenuation=AttenuationConfig(
            enabled=bool(getattr(config, "channel_attenuation_enabled", True)),
            strength=float(getattr(config, "channel_attenuation_strength", 1.0)),
            model=str(getattr(config, "channel_attenuation_model", "Atmospheric")),
        ),
        turbulence=float(getattr(config, "turbulence", 0)),
        beam_wander=float(getattr(config, "channel_beam_wander", 1.0)),
        beam_spread=float(getattr(config, "channel_beam_spread", 1.0)),
        intensity_fluctuation=float(getattr(config, "channel_intensity_fluctuation", 1.0)),
        enabled=bool(getattr(config, "channel_enabled", True)),
    )


class OpticalDisturbanceSubsystem:
    """Beam-state Propagation Channel + residual image-space rendering."""

    def __init__(self, config):
        self.config = config
        self.turbulence_state = TurbulenceState()
        self.channel: PropagationChannel = _channel_from_config(config)
        self._channel_cfg_version: int | None = None

    def _config_version(self) -> int | None:
        """Cheap change detector — avoids rebuilding channel every apply."""
        cfg = self.config
        try:
            return hash((
                str(getattr(cfg, "atmospheric_preset", "Clear")),
                round(float(getattr(cfg, "channel_severity", 1.0)), 4),
                round(float(getattr(cfg, "turbulence", 0.0)), 4),
                round(float(getattr(cfg, "channel_beam_wander", 1.0)), 4),
                round(float(getattr(cfg, "channel_beam_spread", 1.0)), 4),
                round(float(getattr(cfg, "channel_intensity_fluctuation", 1.0)), 4),
                round(float(getattr(cfg, "channel_attenuation_strength", 1.0)), 4),
                str(getattr(cfg, "channel_attenuation_model", "Atmospheric")),
                bool(getattr(cfg, "channel_enabled", True)),
                bool(getattr(cfg, "channel_attenuation_enabled", True)),
            ))
        except (AttributeError, TypeError, ValueError):
            return None

    def _sync_channel(self) -> None:
        ver = self._config_version()
        if ver is not None and ver == self._channel_cfg_version:
            return  # unchanged — keep temporal OU state, skip rebuild
        cfg = self.config
        try:
            fresh = _channel_from_config(cfg)
            # Preserve temporal OU state across config syncs.
            fresh.wander_state = self.channel.wander_state
            fresh.state.beamWander = self.channel.state.beamWander
            fresh.state.intensityFactor = self.channel.state.intensityFactor
            self.channel = fresh
            self._channel_cfg_version = ver
        except (AttributeError, TypeError, ValueError):
            pass

    # ---- Beam-state stage (authoritative per §2/§17) ----
    def propagate_beam(
        self,
        beam: OpticalBeamState,
        context,
        distance_m: float | None = None,
    ) -> ReceivedOpticalState:
        self._sync_channel()
        if not bool(getattr(self.config, "global_enabled", getattr(getattr(self.config, "global_", None), "enabled", True))):
            beam_out = OpticalBeamState(**{k: getattr(beam, k) for k in
                                           ("emittedIntensity", "position", "direction", "spotSize",
                                            "wavelength_nm", "power_w")})
            return ReceivedOpticalState(
                intensity=float(beam_out.emittedIntensity),
                position=tuple(beam_out.position),
                direction=tuple(beam_out.direction),
                spotSize=float(beam_out.spotSize),
            )
        return self.channel.propagate_beam(beam, dt=float(getattr(context, "dt", 1.0 / 30.0)),
                                           rng=getattr(context, "rng", None), distance_m=distance_m)

    # ---- Image-space rendering of the received state (residual) ----
    def apply(self, frame, context):
        """Residual background rendering — beam spots already carry channel.

        Beam-state-only contract: beacons are degraded in
        ``propagate_beam``/``apply_to_patch`` (attenuation, wander, spread,
        scintillation). This image stage renders only the *background*
        residual (seeing blur, haze veil, rain). To avoid double-counting
        scintillation on beacons, image-space scintillation gain is disabled
        whenever the beam channel is active (legacy direct calls to
        ``apply_turbulence`` keep full behavior).
        """
        cfg = self.config
        self._sync_channel()
        channel_on = bool(getattr(cfg, "channel_enabled", True)) and float(
            getattr(cfg, "channel_severity", 1.0) or 0.0) > 1e-9
        out = apply_turbulence(
            frame, int(getattr(cfg, "turbulence", 0)),
            dt=context.dt, rng=context.rng, state=self.turbulence_state,
            apply_scintillation=not channel_on,
        )
        preset = str(getattr(cfg, "atmospheric_preset", "Clear"))
        contrast = float(getattr(cfg, "atmospheric_contrast", 0.0))
        brightness = float(getattr(cfg, "atmospheric_brightness", 0.0))
        # Drive residual contrast/brightness from channel factors when the
        # channel is enabled so image rendering matches beam-state losses.
        try:
            if bool(getattr(cfg, "channel_enabled", True)):
                ch = self.channel
                contrast = float((1.0 - ch.state.contrastFactor) * 100.0)
                brightness = float((1.0 - ch.state.brightnessFactor) * 100.0)
        except (AttributeError, TypeError, ValueError):
            pass
        if preset != "Clear" or contrast > 0 or brightness > 0:
            out = apply_atmospheric_disturbance(
                out, preset=preset, contrast_reduction=contrast,
                brightness_reduction=brightness, rng=context.rng,
            )
        return out

    def channel_state_dict(self) -> dict:
        try:
            return self.channel.telemetry()
        except (AttributeError, TypeError, ValueError):
            return {}

    def reset(self) -> None:
        self.turbulence_state.clear()
        self._channel_cfg_version = None
        try:
            self.channel.reset()
        except (AttributeError, TypeError, ValueError):
            pass


__all__ = ["OpticalDisturbanceSubsystem"]
