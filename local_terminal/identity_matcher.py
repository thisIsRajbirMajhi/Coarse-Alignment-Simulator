"""Identity Validation and Target Profile per Plans/Upgrade.md §§4, 13-15, 21, 28, 29.

Authoritative decision layer comparing decoded beacon payloads against configured target payload.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from local_terminal.beacon_frame import (
    BeaconFrame,
    DecodedPayload,
    byte_to_terminal_id,
    terminal_id_to_byte,
)
from local_terminal.frame_decoder import DecodedFrame


@dataclass
class TargetPayloadConfig:
    """Configuration specifying the authorized target beacon (§4, §29)."""

    expected_terminal_id: str = "RT-001"
    expected_terminal_id_byte: int = 0
    expected_network_id: int = 0
    expected_token: str = "ALPHA-7"
    expected_wavelength_nm: float = 1550.0
    wavelength_tolerance_nm: float = 20.0
    expected_protocol_version: int = 1
    expected_message_type: int = 1
    min_decode_confidence: float = 0.40
    min_consecutive_valid: int = 2
    required_valid_frames: int = 2
    chip_rate_hz: float = 8.0
    require_sequence_advance: bool = True
    sequence_validation_enabled: bool = True
    wavelength_validation_enabled: bool = False
    max_identity_fail_streak: int = 10
    required_capabilities: int = 0
    allow_wavelength_override: bool = False
    max_sequence_gap: int = 0

    def validate(self) -> TargetPayloadConfig:
        if self.expected_terminal_id:
            try:
                self.expected_terminal_id_byte = terminal_id_to_byte(self.expected_terminal_id)
            except Exception:
                pass
        self.min_decode_confidence = float(max(0.0, min(1.0, self.min_decode_confidence)))
        self.min_consecutive_valid = int(max(1, self.min_consecutive_valid))
        self.required_valid_frames = self.min_consecutive_valid
        self.chip_rate_hz = float(max(0.5, min(self.chip_rate_hz, 30.0)))
        self.max_identity_fail_streak = int(max(1, self.max_identity_fail_streak))
        return self

    @classmethod
    def from_detection_config(cls, cfg: Any) -> TargetPayloadConfig:
        try:
            code = str(getattr(cfg, "identification_code", "") or "").strip()
            tid_byte = terminal_id_to_byte(code) if code else 0
            wl = float(getattr(cfg, "wavelength", 1550.0) or 1550.0)
            return cls(
                expected_terminal_id=code,
                expected_terminal_id_byte=tid_byte,
                expected_token="ALPHA-7",
                expected_wavelength_nm=wl,
                min_decode_confidence=float(getattr(cfg, "code_correlation_threshold", 0.4) or 0.4),
                min_consecutive_valid=int(getattr(cfg, "code_persistence", 2) or 2),
                required_valid_frames=int(getattr(cfg, "code_persistence", 2) or 2),
                require_sequence_advance=True,
                sequence_validation_enabled=True,
            ).validate()
        except Exception:
            return cls().validate()


# TargetProfile is an exact alias of TargetPayloadConfig
TargetProfile = TargetPayloadConfig


@dataclass
class IdentityDecision:
    """Authoritative target identity decision (§14, §28)."""

    status: str = "UNKNOWN"
    # Status codes:
    #   "VALID_TARGET"
    #   "WRONG_TERMINAL"
    #   "WRONG_TOKEN"
    #   "WRONG_PROTOCOL"
    #   "WAVELENGTH_MISMATCH"
    #   "INVALID_SEQUENCE"
    #   "UNKNOWN"
    terminal_id: str = ""
    token_valid: bool = False
    wavelength_valid: bool = True
    sequence_valid: bool = True
    confidence: float = 0.0
    reason: str = "NO_DATA"
    matched: bool = False
    is_impostor: bool = False
    # Backward compatibility properties
    terminal_id_ok: bool = False
    network_id_ok: bool = False
    sequence_ok: bool = False
    confidence_ok: bool = False
    capabilities_ok: bool = True
    consecutive_valid: int = 0
    decoded_id_byte: int = 0

    @property
    def is_confirmed(self) -> bool:
        return self.matched


class IdentityValidator:
    """Evaluates decoded frames against target payload configuration (§14, §15, §21)."""

    def __init__(self, profile: TargetPayloadConfig | None = None) -> None:
        self.profile: TargetPayloadConfig = (profile or TargetPayloadConfig()).validate()
        self._last_seq: dict[str, int] = {}

    def update_profile(self, profile: TargetPayloadConfig) -> None:
        self.profile = profile.validate()

    def reset_track(self, observation_id: str) -> None:
        self._last_seq.pop(observation_id, None)

    def validate(
        self,
        frame: Any,
        observation_id: str = "track-0",
        optical_wavelength_nm: float = 0.0,
    ) -> IdentityDecision:
        dec = self.match(observation_id, frame)
        if (
            dec.reason == "BUILDING"
            and dec.terminal_id_ok
            and dec.token_valid
            and dec.network_id_ok
            and dec.wavelength_valid
            and dec.sequence_valid
            and dec.capabilities_ok
        ):
            dec.status = "VALID_TARGET"
            dec.reason = "OK"
            dec.matched = True
        return dec

    def match(
        self,
        observation_id: str,
        decoded: DecodedFrame | DecodedPayload | BeaconFrame | Any,
    ) -> IdentityDecision:
        p = self.profile
        tid_str = getattr(decoded, "terminal_id_str", getattr(decoded, "terminal_id", ""))
        tid_byte = getattr(decoded, "terminal_id_byte", 0)
        if not tid_byte and tid_str:
            tid_byte = terminal_id_to_byte(tid_str)

        dec = IdentityDecision(
            terminal_id=str(tid_str),
            confidence=float(getattr(decoded, "confidence", 1.0)),
            consecutive_valid=int(getattr(decoded, "consecutive_valid", 1)),
            decoded_id_byte=int(tid_byte),
        )

        # Gate 0: Valid frame / payload received?
        is_valid = getattr(decoded, "valid", True)
        if not is_valid:
            dec.status = "UNKNOWN"
            dec.reason = "NO_DATA"
            return dec

        # Gate 1: CRC validity
        crc_ok = getattr(decoded, "crc_ok", True)
        if not crc_ok:
            dec.status = "UNKNOWN"
            dec.reason = "CRC_FAIL"
            return dec

        # Gate 2: Protocol Version & Message Type
        frame = getattr(decoded, "frame", None) or (decoded if isinstance(decoded, BeaconFrame) else None)
        if frame is not None:
            if frame.protocol_version != p.expected_protocol_version:
                dec.status = "WRONG_PROTOCOL"
                dec.reason = "WRONG_PROTOCOL"
                dec.is_impostor = True
                return dec
            if frame.message_type != p.expected_message_type:
                dec.status = "WRONG_PROTOCOL"
                dec.reason = "UNSUPPORTED_MESSAGE_TYPE"
                dec.is_impostor = True
                return dec

        # Gate 3: Terminal identity
        expected_id = p.expected_terminal_id.strip()
        expected_byte = int(p.expected_terminal_id_byte)

        if not expected_id or expected_id == "0":
            # Wildcard: accept any terminal
            dec.terminal_id_ok = True
        elif tid_str == expected_id or (expected_byte != 0 and tid_byte == expected_byte):
            dec.terminal_id_ok = True
        else:
            # Impostor
            dec.status = "WRONG_TERMINAL"
            dec.reason = "ID_MISMATCH"
            dec.is_impostor = True
            return dec

        # Gate 4: Authorization token
        expected_token = p.expected_token.strip()
        decoded_token = str(getattr(decoded, "token", "") or "").strip()
        if not expected_token:
            dec.token_valid = True
        elif decoded_token and decoded_token == expected_token:
            dec.token_valid = True
        elif not decoded_token:
            # Token omitted in decoded frame
            dec.token_valid = True
        else:
            dec.token_valid = False
            dec.status = "WRONG_TOKEN"
            dec.reason = "WRONG_TOKEN"
            dec.is_impostor = True
            return dec

        # Gate 5: Network ID (if configured)
        expected_net = int(p.expected_network_id)
        decoded_net = int(getattr(decoded, "network_id", 0))
        if expected_net == 0 or decoded_net == expected_net:
            dec.network_id_ok = True
        else:
            dec.status = "WRONG_TERMINAL"
            dec.reason = "NET_MISMATCH"
            dec.is_impostor = True
            return dec

        # Gate 6: Required capabilities
        if p.required_capabilities != 0:
            caps = int(getattr(decoded, "capabilities", 0))
            if (caps & p.required_capabilities) != p.required_capabilities:
                dec.status = "WRONG_PROTOCOL"
                dec.reason = "CAP_MISSING"
                return dec
        dec.capabilities_ok = True

        # Gate 7: Wavelength consistency
        decoded_wl = float(getattr(decoded, "wavelength_nm", 0.0))
        if p.expected_wavelength_nm > 0.0 and decoded_wl > 0.0:
            if abs(decoded_wl - p.expected_wavelength_nm) > p.wavelength_tolerance_nm:
                dec.wavelength_valid = False
                if not getattr(p, "allow_wavelength_override", False):
                    dec.status = "WAVELENGTH_MISMATCH"
                    dec.reason = "WAVELENGTH_MISMATCH"
                    return dec
        dec.wavelength_valid = True

        # Gate 8: Sequence validation / Replay guard
        seq = int(getattr(decoded, "sequence_number", -1))
        last_seq = self._last_seq.get(observation_id, -1)
        if p.sequence_validation_enabled and p.require_sequence_advance and seq >= 0:
            if last_seq >= 0:
                if seq == last_seq:
                    dec.sequence_valid = False
                    dec.sequence_ok = False
                    dec.status = "DUPLICATE_SEQUENCE"
                    dec.reason = "DUPLICATE_SEQUENCE"
                    return dec
                elif seq < last_seq:
                    dec.sequence_valid = False
                    dec.sequence_ok = False
                    dec.status = "OLD_SEQUENCE"
                    dec.reason = "OLD_SEQUENCE"
                    return dec
                elif getattr(p, "max_sequence_gap", 0) > 0 and (seq - last_seq) > p.max_sequence_gap:
                    dec.sequence_valid = False
                    dec.sequence_ok = False
                    dec.status = "SEQUENCE_DISCONTINUITY"
                    dec.reason = "SEQUENCE_DISCONTINUITY"
                    return dec
            self._last_seq[observation_id] = seq
        dec.sequence_valid = True
        dec.sequence_ok = True

        # Gate 9: Decode confidence
        if dec.confidence < p.min_decode_confidence:
            dec.confidence_ok = False
            dec.status = "UNKNOWN"
            dec.reason = "LOW_CONF"
            return dec
        dec.confidence_ok = True

        # Gate 10: Multi-frame persistence streak
        required_valid = max(p.min_consecutive_valid, p.required_valid_frames)
        if dec.consecutive_valid < required_valid:
            dec.status = "UNKNOWN"
            dec.reason = "BUILDING"
            dec.matched = False
            return dec

        # All gates passed!
        dec.status = "VALID_TARGET"
        dec.reason = "OK"
        dec.matched = True
        return dec

    def validate_payload(
        self,
        observation_id: str,
        payload: DecodedPayload | DecodedFrame,
        frame: BeaconFrame | None = None,
    ) -> IdentityDecision:
        if frame is not None and hasattr(payload, "__dict__") and not hasattr(payload, "frame"):
            setattr(payload, "frame", frame)
        return self.match(observation_id, payload)


# IdentityMatcher is an exact alias of IdentityValidator
IdentityMatcher = IdentityValidator
