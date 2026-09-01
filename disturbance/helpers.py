# disturbance/helpers.py - Shared physics helpers — r0 and Rytov mappings from intensity

import numpy as np

from disturbance.constants import R0_0, R0_BETA, R0_MAX, R0_MIN

def r0_from_intensity(intensity: float, wavelength: float = 1.55e-6) -> float:
    """
    Map slider intensity [0,10] → Fried r0 [m].

    Physics: r0 = [0.423 k² Cn² L]^{-3/5}, k=2π/λ.
    Empirical slider mapping: r0(I)=r0_0·(1+β·I)^{-0.6} with r0_0=0.18, β=1.1
    → r0∈[0.18, 0.021] m at 1550 nm (weak→strong). Clipped to [0.015,0.5].

    Returns inf when intensity ≤0 (no turbulence).
    """
    if intensity <= 0:
        return float("inf")
    r0 = R0_0 * (1.0 + R0_BETA * float(intensity)) ** (-0.6)
    return float(np.clip(r0, R0_MIN, R0_MAX))

def rytov_variance(intensity: float) -> float:
    """
    Rytov variance σ_R² ≈ 0.5·(I/5)^{1.65} (empirical 0..1.8).

    True: σ_R²=1.23 Cn² k^{7/6} L^{11/6}. We proxy via r0 mapping.
    """
    if intensity <= 0:
        return 0.0
    return float(0.5 * (float(intensity) / 5.0) ** 1.65)