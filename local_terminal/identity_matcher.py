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


from local_terminal.config import TargetPayloadConfig, TargetProfile


class CanonicalStatus(str):
    """String subclass that matches both specific sequence reason and canonical INVALID_SEQUENCE (§18)."""

    def __new__(cls, value: str, canonical: str = "INVALID_SEQUENCE") -> CanonicalStatus:
        obj = str.__new__(cls, value)
        obj._canonical = str(canonical)
        return obj

    def __eq__(self, other: Any) -> bool:
        if super().__eq__(other):
            return True
        return self._canonical == other

    def __hash__(self) -> int:
        return super().__hash__()


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
        dec = self.match(observation_id, frame, optical_wavelength_nm=optical_wavelength_nm)
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
        optical_wavelength_nm: float = 0.0,
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

        # Gate 4: Authorization token (§19 - strict checking)
        expected_token = p.expected_token.strip()
        decoded_token = str(getattr(decoded, "token", "") or "").strip()
        if not expected_token:
            dec.token_valid = True
        elif decoded_token and decoded_token == expected_token:
            dec.token_valid = True
        elif not decoded_token:
            # Token missing when expected (§19: missing token != valid)
            dec.token_valid = False
            dec.status = "WRONG_TOKEN"
            dec.reason = "MISSING_TOKEN"
            dec.is_impostor = True
            return dec
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

        # Gate 7: Wavelength consistency (§20)
        decoded_wl = float(getattr(decoded, "wavelength_nm", 0.0))
        if p.expected_wavelength_nm > 0.0 and decoded_wl > 0.0 and getattr(p, "wavelength_validation_enabled", True):
            if abs(decoded_wl - p.expected_wavelength_nm) > p.wavelength_tolerance_nm:
                dec.wavelength_valid = False
                if not getattr(p, "allow_wavelength_override", False):
                    dec.status = "WAVELENGTH_MISMATCH"
                    dec.reason = "WAVELENGTH_MISMATCH"
                    return dec
        if optical_wavelength_nm > 0.0 and p.expected_wavelength_nm > 0.0 and getattr(p, "wavelength_validation_enabled", True):
            if abs(optical_wavelength_nm - p.expected_wavelength_nm) > max(p.wavelength_tolerance_nm, 50.0):
                dec.wavelength_valid = False
                if not getattr(p, "allow_wavelength_override", False):
                    dec.status = "WAVELENGTH_MISMATCH"
                    dec.reason = "OPTICAL_WAVELENGTH_MISMATCH"
                    return dec
        dec.wavelength_valid = True

        # Gate 8: Sequence validation / Replay guard (§18)
        seq = int(getattr(decoded, "sequence_number", -1))
        last_seq = self._last_seq.get(observation_id, -1)
        if p.sequence_validation_enabled and p.require_sequence_advance and seq >= 0:
            if last_seq >= 0:
                if seq == last_seq:
                    dec.sequence_valid = False
                    dec.sequence_ok = False
                    dec.status = CanonicalStatus("DUPLICATE_SEQUENCE", "INVALID_SEQUENCE")
                    dec.reason = "DUPLICATE_SEQUENCE"
                    return dec
                elif seq < last_seq:
                    dec.sequence_valid = False
                    dec.sequence_ok = False
                    dec.status = CanonicalStatus("OLD_SEQUENCE", "INVALID_SEQUENCE")
                    dec.reason = "OLD_SEQUENCE"
                    return dec
                elif getattr(p, "max_sequence_gap", 0) > 0 and (seq - last_seq) > p.max_sequence_gap:
                    dec.sequence_valid = False
                    dec.sequence_ok = False
                    dec.status = CanonicalStatus("SEQUENCE_DISCONTINUITY", "INVALID_SEQUENCE")
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
