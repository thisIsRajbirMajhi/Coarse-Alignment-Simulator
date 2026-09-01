# disturbance/sensor_noise.py - Physics sensor model — s/read/PRNU/ pixels, well-commented

import numpy as np

from disturbance.constants import ELECTRONS_PER_DN, READ_SIGMA_BASE, T_EXP

def apply_sensor_noise(
    frame: np.ndarray,
    intensity: float,
    electrons_per_dn: float = ELECTRONS_PER_DN,
    read_sigma_base: float = READ_SIGMA_BASE,
) -> np.ndarray:
    """
    Physics sensor model (InGaAs / CMOS @ 1550 nm).

    Model:
      electrons = DN·g + dark(D·t)          g=electrons_per_dn
      shot ~ Poisson(electrons)             Var = electrons
      read ~ N(0, σ_r), σ_r = σ0 + 2.0·I    I=intensity [0,10]
      PRNU ~ N(1, 0.015·I/10) per-pixel gain
      hot pixels 0.02% at I>6

    intensity [0,10] → σ_r 1.2→21 DN, dark 12→800 e.
    Stateless — no dt needed, no global state.
    """
    if intensity <= 0 or frame.size == 0:
        return frame
    h, w = frame.shape[:2]

    # DN → electrons
    dn_f = frame.astype(np.float32)
    electrons = dn_f * float(electrons_per_dn)

    # Dark current: D·t, t_exp≈33 ms → scaled with intensity
    dark_e = (6.0 + float(intensity) * 3.5) * float(T_EXP) * 60.0
    electrons = electrons + float(dark_e)

    # Poisson s — vectorized, with Normal approx for large λ or large frames
    flat = electrons.reshape(-1)
    large = flat > 3000
    shot = np.empty_like(flat)
    if np.any(~large):
        lam = np.clip(flat[~large], 0, 9000)
        if lam.size > 500_000:
            shot[~large] = np.random.normal(lam, np.sqrt(np.maximum(lam, 1)))
        else:
            shot[~large] = np.random.poisson(lam).astype(float)
    if np.any(large):
        lam = flat[large]
        shot[large] = np.random.normal(lam, np.sqrt(lam))
    shot = shot.reshape(electrons.shape)

    # Read noise — Gaussian white
    sigma_r_e = (float(read_sigma_base) + float(intensity) * 2.0) * float(electrons_per_dn)
    read = np.random.normal(0.0, sigma_r_e, shot.shape)
    electrons_noisy = shot + read

    # PRNU — per-pixel gain variation
    if intensity > 0.5:
        prnu_sigma = 0.015 * (float(intensity) / 10.0)
        prnu = np.random.normal(1.0, prnu_sigma, (h, w)).astype(np.float32)
        prnu = np.clip(prnu, 0.92, 1.08)
        for c in range(frame.shape[2] if frame.ndim == 3 else 1):
            if frame.ndim == 3:
                electrons_noisy[:, :, c] *= prnu
            else:
                electrons_noisy[:] *= prnu

    # Back to DN, pixels, quantise
    dn_out = electrons_noisy / float(electrons_per_dn)
    if intensity > 6 and np.random.random() < 0.35:
        n_hot = int(h * w * 0.0002 * (float(intensity) - 6) / 4)
        ys = np.random.randint(0, h, size=n_hot)
        xs = np.random.randint(0, w, size=n_hot)
        hot_val = np.random.randint(220, 255, size=n_hot)
        if frame.ndim == 3:
            dn_out[ys, xs, :] = hot_val[:, None] if hot_val.ndim == 1 else hot_val
        else:
            dn_out[ys, xs] = hot_val

    dn_out = np.clip(np.round(dn_out), 0, 255).astype(np.uint8)
    if frame.ndim == 2:
        dn_out = dn_out[:, :, 0] if dn_out.ndim == 3 else dn_out
    return dn_out.astype(frame.dtype, copy=False)