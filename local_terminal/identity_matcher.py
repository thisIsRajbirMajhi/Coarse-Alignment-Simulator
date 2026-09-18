# local_terminal/identity_matcher.py - Module: Identity Matcher
#
# Compares a DecodedFrame against the local TargetProfile to decide
# whether a candidate is the expected target.
#
# Decision rules (all must pass for matched=True):
#   1. Frame is CRC-valid
#   2. decoded terminal_id_byte == expected  (or expected is wildcard 0)
#   3. decoded network_id == expected        (or expected is wildcard 0)
#   4. sequence_number != last_accepted_seq  (replay-attack guard, optional)
#   5. decoded.confidence >= min_decode_confidence
#
# Optical signature (wavelength, spot size, SNR) is NOT checked here;
# that remains in SignatureAnalyzer as a quality gate.
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from local_terminal.frame_decoder import DecodedFrame


# ── TargetProfile / TargetPayloadConfig ──────────────────────────────────────
@dataclass
class TargetProfile:
    """What the local terminal expects to decode from the target beacon.

    Configured locally; never fetched from a RemoteTerminal object.
    """
    # Expected remote terminal ID.  0 = accept any (wildcard).
    expected_terminal_id_byte: int   = 0
    # Convenience: string form automatically converted to byte on validate().
    expected_terminal_id: str        = ""
    # Expected network/group. 0 = accept any.
    expected_network_id:  int        = 0
    # Expected authorization token (optional)
    expected_token:       str        = ""
    # Expected nominal wavelength (nm) for consistency check
    expected_wavelength_nm: float    = 0.0
    expected_protocol_version: int   = 1
    expected_message_type: int       = 1
    # Minimum decoded.confidence to accept a frame as identity evidence.
    min_decode_confidence: float     = 0.40
    # Minimum consecutive valid decoded frames before declaring IDENTIFIED.
    min_consecutive_valid: int       = 2
    required_valid_frames: int       = 2
    # Chip rate (Hz) expected for OOK demodulation
    chip_rate_hz:          float     = 8.0
    # Guard against replay: reject if sequence number did not advance.
    require_sequence_advance: bool   = True
    sequence_validation_enabled: bool = True
    wavelength_validation_enabled: bool = False
    # Tracking identity retention tolerance
    max_identity_fail_streak: int    = 10
    # Capabilities that MUST be present in the decoded capabilities byte.
    # 0 = no capability requirement.
    required_capabilities: int       = 0

    def validate(self) -> "TargetProfile":
        # Resolve string ID → byte
        if self.expected_terminal_id:
            from local_terminal.beacon_frame import terminal_id_to_byte
            self.expected_terminal_id_byte = terminal_id_to_byte(self.expected_terminal_id)
        self.min_decode_confidence = float(
            max(0.0, min(1.0, self.min_decode_confidence)))
        self.min_consecutive_valid = int(max(1, self.min_consecutive_valid))
        self.required_valid_frames = self.min_consecutive_valid
        self.chip_rate_hz = float(max(0.5, min(self.chip_rate_hz, 30.0)))
        self.max_identity_fail_streak = int(max(1, self.max_identity_fail_streak))
        return self

    @classmethod
    def from_detection_config(cls, cfg: Any) -> "TargetProfile":
        """Build from existing DetectionConfig for backward compatibility."""
        try:
            code = str(getattr(cfg, "identification_code", "") or "")
            from local_terminal.beacon_frame import terminal_id_to_byte
            tid_byte = terminal_id_to_byte(code) if code else 0
            return cls(
                expected_terminal_id_byte=tid_byte,
                expected_terminal_id=code,
                expected_network_id=0,
                min_decode_confidence=float(
                    getattr(cfg, "code_correlation_threshold", 0.4) or 0.4),
                min_consecutive_valid=int(
                    getattr(cfg, "code_persistence", 2) or 2),
                require_sequence_advance=True,
            ).validate()
        except Exception:
            return cls().validate()


# ── IdentityDecision ─────────────────────────────────────────────────────────
@dataclass
class IdentityDecision:
    """Result of matching a decoded frame against the TargetProfile."""
    matched:           bool  = False
    terminal_id_ok:    bool  = False
    network_id_ok:     bool  = False
    sequence_ok:       bool  = False
    confidence_ok:     bool  = False
    capabilities_ok:   bool  = False
    consecutive_valid: int   = 0
    confidence:        float = 0.0
    decoded_id_byte:   int   = 0
    reason: str = "NO_DATA"
    # Reason codes:
    #   "NO_DATA"       — no valid frame decoded yet
    #   "OK"            — all checks passed
    #   "ID_MISMATCH"   — terminal_id_byte mismatch
    #   "NET_MISMATCH"  — network_id mismatch
    #   "REPLAY"        — sequence number repeated (replay guard)
    #   "LOW_CONF"      — confidence below threshold
    #   "CAP_MISSING"   — required capabilities absent
    #   "CRC_FAIL"      — latest frame failed CRC

    @property
    def is_impostor(self) -> bool:
        """A decode succeeded but the identity clearly does not match."""
        return self.reason in ("ID_MISMATCH", "NET_MISMATCH")

    @property
    def is_confirmed(self) -> bool:
        return self.matched


# ── IdentityMatcher ──────────────────────────────────────────────────────────
class IdentityMatcher:
    """Compares a DecodedFrame against a TargetProfile → IdentityDecision.

    Per-track state: tracks last accepted sequence number to detect replays.
    """

    def __init__(self, profile: TargetProfile | None = None) -> None:
        self.profile: TargetProfile = (profile or TargetProfile()).validate()
        self._last_seq: dict[str, int] = {}   # {observation_id: last_seq}

    def update_profile(self, profile: TargetProfile) -> None:
        self.profile = profile.validate()

    def reset_track(self, observation_id: str) -> None:
        self._last_seq.pop(observation_id, None)

    def match(
        self,
        observation_id: str,
        decoded: DecodedFrame,
    ) -> IdentityDecision:
        """Evaluate identity of a decoded frame for a given track.

        Returns an IdentityDecision with matched=True only when ALL
        configured gates pass.
        """
        p = self.profile
        dec = IdentityDecision(
            confidence=float(decoded.confidence),
            consecutive_valid=int(decoded.consecutive_valid),
            decoded_id_byte=int(decoded.terminal_id_byte),
        )

        # Gate 0: was a valid frame decoded at all?
        if not decoded.valid:
            dec.reason = "NO_DATA"
            return dec

        # Gate 1: CRC validity
        if not decoded.crc_ok:
            dec.reason = "CRC_FAIL"
            return dec

        # Gate 2: terminal identity
        expected_id = int(p.expected_terminal_id_byte)
        if expected_id == 0:
            dec.terminal_id_ok = True   # wildcard
        elif decoded.terminal_id_byte == expected_id:
            dec.terminal_id_ok = True
        else:
            dec.reason = "ID_MISMATCH"
            return dec   # hard reject — wrong terminal

        # Gate 3: network identity
        expected_net = int(p.expected_network_id)
        if expected_net == 0:
            dec.network_id_ok = True    # wildcard
        elif decoded.network_id == expected_net:
            dec.network_id_ok = True
        else:
            dec.reason = "NET_MISMATCH"
            return dec   # hard reject — wrong network

        # Gate 4: capabilities
        if p.required_capabilities == 0:
            dec.capabilities_ok = True
        elif (decoded.capabilities & p.required_capabilities) == p.required_capabilities:
            dec.capabilities_ok = True
        else:
            dec.reason = "CAP_MISSING"
            return dec

        # Gate 5: replay guard
        last_seq = self._last_seq.get(observation_id, -1)
        if p.require_sequence_advance:
            if decoded.sequence_number == last_seq:
                dec.reason = "REPLAY"
                return dec
        dec.sequence_ok = True
        self._last_seq[observation_id] = decoded.sequence_number

        # Gate 6: decode confidence
        if decoded.confidence < p.min_decode_confidence:
            dec.confidence_ok = False
            dec.reason = "LOW_CONF"
            return dec
        dec.confidence_ok = True

        # Gate 7: consecutive valid frames
        if decoded.consecutive_valid < p.min_consecutive_valid:
            dec.reason = "BUILDING"  # accumulating evidence, not yet confirmed
            dec.matched = False
            return dec

        # All gates passed
        dec.matched = True
        dec.reason = "OK"
        return dec


# ── Aliases per Upgrade.md §13, §14, §29 ─────────────────────────────────────
TargetPayloadConfig = TargetProfile
IdentityValidator = IdentityMatcher


@dataclass
class DecodedPayload:
    """Standard decoded beacon payload per Upgrade.md §13."""
    terminal_id: str = ""
    token: str = ""
    wavelength_nm: float = 0.0
    sequence_number: int = -1

