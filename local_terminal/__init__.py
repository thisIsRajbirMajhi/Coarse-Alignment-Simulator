"""
Package: local_terminal — V2 FSOC autonomy (Plan V2).
Public V2 API: models, detector, association, identity, tracker, selector,
               reacquisition, supervisor, scan, comm_receiver, registry.
"""
from local_terminal.association import AssociationResult, associate_acquisition, associate_tracking
from local_terminal.comm_receiver import BUFFER_CHIPS, CHIP_DT_S, CommReceiver, CommSource, ber_from_snr_db, decode_to_observation
from local_terminal.detector import ClassicalSpotDetector, SpotDetector, TemporalConfirmer, detect_spots
from local_terminal.identity import IdentityConfig, IdentityResult, IdentityValidator
from local_terminal.models import AutonomyConfig, BeaconObservation, SpotCandidate, TargetObservation, TargetTrack
from local_terminal.reacquisition import V2ReacqResult, V2Reacquisition
from local_terminal.registry import ExpectedSignature, SignatureRegistry, WAVELENGTH_BAND_MAX_NM, WAVELENGTH_BAND_MIN_NM, WAVELENGTH_TOLERANCE_NM
from local_terminal.scan import GRID_COLS, GRID_ROWS, TOTAL_POSITIONS, ScanConfig, ScanController, ScanPosition, build_grid
from local_terminal.selector import select_active_v2
from local_terminal.supervisor import SupervisorV2, V2Output, V2State
from local_terminal.tracker import KalmanConfig, KalmanFilter2D, KalmanTracker, r_for_snr

__all__ = [
    "SpotCandidate", "BeaconObservation", "TargetObservation", "TargetTrack", "AutonomyConfig",
    "detect_spots", "TemporalConfirmer", "SpotDetector", "ClassicalSpotDetector",
    "AssociationResult", "associate_acquisition", "associate_tracking",
    "IdentityValidator", "IdentityConfig", "IdentityResult",
    "KalmanConfig", "KalmanFilter2D", "KalmanTracker", "r_for_snr",
    "V2ReacqResult", "V2Reacquisition", "select_active_v2",
    "SupervisorV2", "V2State", "V2Output",
    "ScanConfig", "ScanPosition", "ScanController", "build_grid", "GRID_COLS", "GRID_ROWS", "TOTAL_POSITIONS",
    "CommReceiver", "CommSource", "CHIP_DT_S", "BUFFER_CHIPS", "ber_from_snr_db", "decode_to_observation",
    "ExpectedSignature", "SignatureRegistry", "WAVELENGTH_BAND_MAX_NM", "WAVELENGTH_BAND_MIN_NM", "WAVELENGTH_TOLERANCE_NM",
]
