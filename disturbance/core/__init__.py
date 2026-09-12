"""Shared disturbance infrastructure with lazy public exports."""

__all__ = [
	"DisturbanceContext", "DisturbancePipeline", "DisturbanceRng", "DisturbanceState",
	"TurbulenceState", "VibrationState", "CameraDriftState", "PlatformMotionState",
	"JitterState", "SensorDefectState", "DisturbanceScenarioGenerator",
]


def __getattr__(name):
	if name == "DisturbanceContext":
		from disturbance.core.context import DisturbanceContext
		return DisturbanceContext
	if name == "DisturbancePipeline":
		from disturbance.core.pipeline import DisturbancePipeline
		return DisturbancePipeline
	if name == "DisturbanceRng":
		from disturbance.core.rng import DisturbanceRng
		return DisturbanceRng
	if name == "DisturbanceScenarioGenerator":
		from disturbance.core.scenario import DisturbanceScenarioGenerator
		return DisturbanceScenarioGenerator
	if name in {"DisturbanceState", "TurbulenceState", "VibrationState", "CameraDriftState", "PlatformMotionState", "JitterState", "SensorDefectState"}:
		from disturbance.core import state
		return getattr(state, name)
	raise AttributeError(name)