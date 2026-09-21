"""
Package: local_terminal
Purpose: Local-terminal autonomy — image-based detection, tracking, validation,
scan and re-acquisition (Plan.md Phases 1-6, implementation Stages 1-4).
Public API: DetectorConfig, Detection, detect_candidates, ImageTracker.
Notes: Ground-truth isolation — this package may only consume rendered frames
and decoded beams, never simulator truth (positions, states, configs).
"""

from local_terminal.comm_receiver import (
    BUFFER_CHIPS,
    CHIP_DT_S,
    CommReceiver,
    CommSource,
    ber_from_snr_db,
)
from local_terminal.config import LocalTerminalConfig, make_default_local_terminal
from local_terminal.detector import Detection, DetectorConfig, detect_candidates
from local_terminal.motion import AlphaBetaAxis, AlphaBetaConfig, AlphaBetaFilter2D
from local_terminal.registry import (
    WAVELENGTH_BAND_MAX_NM,
    WAVELENGTH_BAND_MIN_NM,
    WAVELENGTH_TOLERANCE_NM,
    ExpectedSignature,
    SignatureRegistry,
)
from local_terminal.reacquisition import (
    EscalationStage,
    ReacquisitionConfig,
    ReacquisitionManager,
    ReacquisitionResult,
)
from local_terminal.scan import (
    GRID_COLS,
    GRID_ROWS,
    TOTAL_POSITIONS,
    ScanConfig,
    ScanController,
    ScanPosition,
    build_grid,
)
from local_terminal.selector import (
    StandbyCandidate,
    StandbyPool,
    TargetSelector,
)
from local_terminal.supervisor import (
    AutonomyState,
    AutonomySupervisor,
    SupervisorConfig,
    SupervisorOutput,
)
from local_terminal.tracker import ImageTracker, TrackerConfig
from local_terminal.validator import (
    SCORE_MIN,
    TrackValidator,
    ValidationConfig,
    ValidationSnapshot,
)

__all__ = [
    "Detection",
    "DetectorConfig",
    "detect_candidates",
    "LocalTerminalConfig",
    "make_default_local_terminal",
    "AlphaBetaAxis",
    "AlphaBetaConfig",
    "AlphaBetaFilter2D",
    "ImageTracker",
    "TrackerConfig",
    "ExpectedSignature",
    "SignatureRegistry",
    "WAVELENGTH_BAND_MIN_NM",
    "WAVELENGTH_BAND_MAX_NM",
    "WAVELENGTH_TOLERANCE_NM",
    "CommReceiver",
    "CommSource",
    "CHIP_DT_S",
    "BUFFER_CHIPS",
    "ber_from_snr_db",
    "TrackValidator",
    "ValidationConfig",
    "ValidationSnapshot",
    "SCORE_MIN",
    "ScanConfig",
    "ScanPosition",
    "ScanController",
    "build_grid",
    "GRID_COLS",
    "GRID_ROWS",
    "TOTAL_POSITIONS",
    "StandbyCandidate",
    "StandbyPool",
    "TargetSelector",
    "EscalationStage",
    "ReacquisitionConfig",
    "ReacquisitionResult",
    "ReacquisitionManager",
    "AutonomyState",
    "SupervisorConfig",
    "SupervisorOutput",
    "AutonomySupervisor",
]
