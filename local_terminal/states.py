# local_terminal/states.py - Dual state systems per Work.md §2 and Plan.md §12, §28.
from __future__ import annotations

from enum import Enum


class LocalTerminalState(str, Enum):
    """Global Local-Terminal state: what the PTZ/system is doing.

    Plan §3 output states + §28 full machine. Includes IDLE/SEARCHING/
    DETECTING/VERIFYING/ACQUIRED/TRACKING/DEGRADED/REACQUIRING/LOST/FAULT.
    """

    IDLE = "IDLE"
    SEARCHING = "SEARCHING"
    DETECTING = "DETECTING"
    DECODING = "DECODING"          # Phase-2: beacon signal being decoded
    VERIFYING = "VERIFYING"        # Phase-2: identity verified, spatial lock pending
    ACQUIRED = "ACQUIRED"
    TRACKING = "TRACKING"
    DEGRADED = "DEGRADED"
    REACQUIRING = "REACQUIRING"
    LOST = "LOST"
    FAULT = "FAULT"

    @classmethod
    def coerce(cls, value: object, default: LocalTerminalState = None) -> LocalTerminalState:
        default = default or LocalTerminalState.IDLE
        if isinstance(value, cls):
            return value
        try:
            return cls(str(value).strip().upper())
        except Exception:
            return default


class CandidateState(str, Enum):
    """Per-observation candidate lifecycle state (Work.md §2B, Plan §12).

    Independent from the global terminal state: e.g. terminal=SEARCHING
    while C1=TENTATIVE, C2=IDENTIFIED, C3=REJECTED simultaneously.
    """

    SEEN = "SEEN"
    TENTATIVE = "TENTATIVE"
    VALIDATING = "VALIDATING"
    # Phase-2 communication-path states
    SIGNAL_DETECTED = "SIGNAL_DETECTED"    # modulated signal observed
    DECODING = "DECODING"                  # actively decoding beacon frames
    IDENTITY_UNKNOWN = "IDENTITY_UNKNOWN"  # decoded but ID not yet confirmed
    IDENTIFIED = "IDENTIFIED"
    SELECTED = "SELECTED"
    ACQUIRED = "ACQUIRED"
    TRACKING = "TRACKING"
    DEGRADED = "DEGRADED"
    REACQUIRING = "REACQUIRING"
    REJECTED = "REJECTED"
    LOST = "LOST"
    EXPIRED = "EXPIRED"

    @classmethod
    def coerce(cls, value: object, default: CandidateState = None) -> CandidateState:
        default = default or CandidateState.SEEN
        if isinstance(value, cls):
            return value
        try:
            return cls(str(value).strip().upper())
        except Exception:
            return default
