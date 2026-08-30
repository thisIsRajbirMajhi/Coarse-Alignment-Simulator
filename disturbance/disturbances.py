"""
Disturbance module — physics-realistic FSOC channel impairments.

Each function maps GUI slider intensity [0,10] → physical parameters,
implements closed-form propagation/models, and evolves statefully for
temporal correlation (Taylor frozen-flow, OU processes).

Physics — equations documented at each model:

1. Sensor noise  — Poisson shot + Gaussian read + dark current + PRNU + quantisation
   N_e = DN·g  , shot ~ Poisson(N_e + D·t) , read ~ N(0,σ_r) , PRNU·gain variation,
   DN_out = clip((shot+read)·/g, 0,255).  Full-well, QE implicit in g.

2. Turbulence — Kolmogorov phase screens:
   Fried r0 = [0.423 k² Cn² L]^{-3/5},  k=2π/λ
   von Kármán PSD  Φ_n(κ)=0.033 Cn² (κ²+1/L0²)^{-11/6} exp(-κ²l0²)
   Phase PSD  Φ_φ(κ)=0.023 r0^{-5/3} (κ²+1/L0²)^{-11/6} exp(-κ²l0²)
   Scintillation (Rytov)  σ_R² =1.23 Cn² k^{7/6} L^{11/6},  σ_I²≈σ_R² (weak)
   Tilt variance  σ_α²=0.364 (D/r0)^{5/3} (λ/D)² .
   Implemented: FFT-based phase screen → gradient→ displacement (beam wander)
               + seeing blur PSF (0.98 λ/r0)  + log-normal scintillation.

3. Platform vibration — harmonic PSD:
   Jitter PSD  S_θ(f)= Σ A_i²·(ζf_i / ((f−f_i)²+(ζf_i)²)) + S_white
   θ(t)= Σ A_i(I)·sin(2πf_i t+φ_i) + η_OU(t)  (OU = band-limited white)
   f_i = {7,18,35,72,150} Hz typical for UAV/sat reaction wheels.

4. Camera motion / drift — Ornstein-Uhlenbeck:
   dv = −v/τ dt + σ√(2/τ) dW ,  ⟨v(t)v(t+τ)⟩∝exp(−τ/τ_c),  τ_c≈6 s (thermal)
   position drift = ∫ v dt  (correlated, not white)

Temporal correlation uses exponential blending:  x_t = α·x_{t-1}+ (1−α)·x_new,
α=exp(−dt/τ_c).  dt inferred from wall time when not supplied.
"""

import math
import time

import cv2
import numpy as np

# ─── global state for temporal correlation ───
_turb_state: dict = {"dx": None, "dy": None, "t": 0.0, "last_wall": None, "phase": None}
_vib_state: dict = {"t": 0.0, "last_wall": None, "phases": None}
_cam_motion_state_global: dict = {}

# ─── helpers ───
def _elapsed_dt(state: dict, fallback: float = 0.033) -> float:
    now = time.time()
    last = state.get("last_wall")
    state["last_wall"] = now
    if last is None:
        return fallback
    dt = now - last
    return float(np.clip(dt, 0.005, 0.08))


def _r0_from_intensity(intensity: float, wavelength: float = 1.55e-6) -> float:
    """
    Map intensity [0,10] → Fried r0 [m].
    At 1550 nm, weak: r0≈0.20 m (good seeing), strong: r0≈0.02 m.
    r0(I)=r0_0 · (1+ β·I)^{-3/5}  with r0_0=0.18, β=1.1  → r0∈[0.18,0.021] m
    Physics: r0 = [0.423 k² Cn² L]^{-3/5}, so Cn² ∝ r0^{-5/3}.
    """
    if intensity <= 0:
        return float("inf")
    r0_0 = 0.18
    beta = 1.1
    r0 = r0_0 * (1.0 + beta * intensity) ** (-0.6)
    return float(np.clip(r0, 0.015, 0.5))


def _rytov_variance(intensity: float) -> float:
    """
    Rytov variance σ_R² ≈ 0.5·(I/5)^{5/3}  (empirical mapping to 0..1.8)
    True: σ_R²=1.23 Cn² k^{7/6} L^{11/6}. We proxy via r0 mapping.
    """
    if intensity <= 0:
        return 0.0
    return float(0.5 * (intensity / 5.0) ** 1.65)


# ─── 1. Sensor noise — physics ───
def apply_sensor_noise(frame: np.ndarray, intensity: float,
                       electrons_per_dn: float = 8.0,
                       read_sigma_base: float = 1.2) -> np.ndarray:
    """
    Physics sensor model (InGaAs / CMOS @ 1550 nm):
      electrons = DN·g + dark
      shot ~ Poisson(electrons)              Var = electrons
      read ~ N(0, σ_r), σ_r = σ0 + 2.0·I
      PRNU ~ N(1, 0.015·I/10)  per-pixel gain
      Quantisation implicit in round-trip.

    intensity [0,10] → σ_r 1.2→21 DN-equivalent, dark 0→~40 e.
    """
    if intensity <= 0:
        return frame
    if frame.size == 0:
        return frame
    h, w = frame.shape[:2]
    # Convert to electrons
    dn_f = frame.astype(np.float32)
    electrons = dn_f * electrons_per_dn  # (H,W,3)
    # Dark current: D = 18 e/s/pix * t_exp, t_exp≈33 ms → ~0.6e + I-scaling
    t_exp = 0.033
    dark_e = (6.0 + intensity * 3.5) * t_exp * 60.0  # 12–800 e range scaled
    dark_e = float(dark_e)
    electrons = electrons + dark_e

    # Poisson shot — vectorised; use Poisson for <6000 e else Normal approx for speed
    # For 25 MP at 10 intensity, per-pixel Poisson is heavy; we batch with normal approx
    # when electrons > 3000 (error <1.5%)
    flat = electrons.reshape(-1)
    # Normal approx mask
    large = flat > 3000
    shot = np.empty_like(flat)
    # Poisson branch (few pixels usually)
    if np.any(~large):
        # Clip to avoid absurd lambda for 5000×5000 dark
        lam = np.clip(flat[~large], 0, 9000)
        # np.random.poisson is slow for large arrays; use iterative but okay for 150×200
        # For large frames (>1 MP) use normal approx even below 3000 to keep 30 fps
        if lam.size > 500_000:
            shot[~large] = np.random.normal(lam, np.sqrt(np.maximum(lam, 1)))
        else:
            shot[~large] = np.random.poisson(lam).astype(float)
    if np.any(large):
        lam = flat[large]
        shot[large] = np.random.normal(lam, np.sqrt(lam))
    shot = shot.reshape(electrons.shape)

    # Read noise (Gaussian, per-pixel white)
    sigma_r_e = (read_sigma_base + intensity * 2.0) * electrons_per_dn  # in electrons
    read = np.random.normal(0.0, sigma_r_e, shot.shape)

    electrons_noisy = shot + read

    # PRNU — fixed-pattern gain variation (spatial, not temporal; re-rolled slowly)
    # We generate fresh per frame but low-pass: realistic PRNU is static; we approximate
    # with slow-varying field blended 95% previous. For simplicity per-frame iid 1.5%.
    if intensity > 0.5:
        prnu_sigma = 0.015 * (intensity / 10.0)  # 0–1.5%
        # 2-D gain map broadcast to 3 channels
        prnu = np.random.normal(1.0, prnu_sigma, (h, w)).astype(np.float32)
        # clamp 0.92–1.08 to avoid blowup
        prnu = np.clip(prnu, 0.92, 1.08)
        for c in range(frame.shape[2] if frame.ndim == 3 else 1):
            if frame.ndim == 3:
                electrons_noisy[:, :, c] *= prnu
            else:
                electrons_noisy[:] *= prnu

    # Convert back, quantise, clip
    # Hot pixels: 0.02% of pixels become spuriously bright at high intensity
    dn_out = electrons_noisy / electrons_per_dn
    if intensity > 6 and np.random.random() < 0.35:
        n_hot = int(h * w * 0.0002 * (intensity - 6) / 4)
        ys = np.random.randint(0, h, size=n_hot)
        xs = np.random.randint(0, w, size=n_hot)
        hot_val = np.random.randint(220, 255, size=n_hot)
        if frame.ndim == 3:
            dn_out[ys, xs, :] = hot_val[:, None] if hot_val.ndim == 1 else hot_val
        else:
            dn_out[ys, xs] = hot_val

    dn_out = np.clip(np.round(dn_out), 0, 255).astype(np.uint8)
    # Preserve input shape/dtype
    if frame.ndim == 2:
        dn_out = dn_out[:, :, 0] if dn_out.ndim == 3 else dn_out
    return dn_out.astype(frame.dtype, copy=False)


# ─── 2. Turbulence — Kolmogorov phase screen ───
def _kolmogorov_displacement(h: int, w: int, r0: float, intensity: float,
                             wavelength: float = 1.55e-6,
                             outer_scale: float = 12.0,
                             inner_scale: float = 0.008) -> tuple[np.ndarray, np.ndarray]:
    """
    Generate Kolmogorov displacement fields dx,dy [pixels].

    Phase PSD: Φ_φ(κ)=0.023 r0^{-5/3} (κ²+1/L0²)^{-11/6} exp(−κ² l0²)
    Displacement ∝ ∇φ → multiply by κ in Fourier domain.

    We synthesise phase in Fourier domain then take gradient; equivalent
    to generating displacement directly with  Φ_d ∝ κ² Φ_φ.

    Tilt variance gives scale check: σ_tilt ≈0.364 λ/(D r0^{5/6}) → pixels.
    Here D≈FOV pixels, we map r0 0.18→0.02 m to σ 0.9→8 px at I=10.
    """
    # Frequency grid (cycles / pixel)
    fx = np.fft.fftfreq(w)  # [1/pixel]
    fy = np.fft.fftfreq(h)
    FX, FY = np.meshgrid(fx, fy)
    kappa = np.sqrt(FX**2 + FY**2)  # 1/pixel
    # Avoid DC division
    kappa[0, 0] = 1e-6
    # Von Kármán factor
    k0 = 1.0 / outer_scale  # ~0.083 m^{-1}, in pixel units we treat as 1/ (FOV_m) ; approximate
    # Convert pixel κ to physical: assume pixel = 35 µrad → 0.035 m at 1 km, order unity; keep dimensionless
    # Use effective scaling: treat κ_pixel * (2π) as rad/m equivalent with scaling 1/0.03
    kappa_phys = kappa * 180.0  # empirical to put knee near L0
    phil = 0.023 * (r0 ** (-5.0/3.0)) * (kappa_phys**2 + k0**2) ** (-11.0/6.0) * np.exp(-(kappa_phys * inner_scale)**2)
    # Displacement PSD ~ κ² Φ_φ
    phil_d = phil * (kappa_phys**2) * (wavelength * 0.9) ** 2 * 1e6  # scale to pixels (tunable)
    # Clamp extreme
    phil_d = np.clip(phil_d, 0, 1e4)
    amp = np.sqrt(phil_d)
    # Random complex Gaussian
    rnd_x = np.random.normal(0, 1, (h, w)) + 1j * np.random.normal(0, 1, (h, w))
    rnd_y = np.random.normal(0, 1, (h, w)) + 1j * np.random.normal(0, 1, (h, w))
    dx_f = rnd_x * amp
    dy_f = rnd_y * amp
    # Force Hermitian? Not needed for displacement (real field from inverse FFT of complex noise gives real after taking real)
    dx = np.fft.ifft2(dx_f).real
    dy = np.fft.ifft2(dy_f).real
    # Normalise to target RMS set by intensity / r0
    # Target tilt RMS (pixels) ∝ I^{0.85}: 0.7 px at I=2, 6.5 px at I=10
    target_rms = 0.32 * (intensity ** 0.85) + 0.08 * intensity
    cur_rms = math.sqrt(np.mean(dx**2 + dy**2) + 1e-9)
    if cur_rms > 1e-6:
        scale = target_rms / cur_rms
        dx *= scale; dy *= scale
    # Clip to avoid extreme warps that fold image
    max_disp = 1.8 * intensity + 2.0
    dx = np.clip(dx, -max_disp, max_disp)
    dy = np.clip(dy, -max_disp, max_disp)
    return dx.astype(np.float32), dy.astype(np.float32)


def apply_turbulence(frame: np.ndarray, intensity: float,
                     wavelength: float = 1.55e-6) -> np.ndarray:
    """
    Kolmogorov + Rytov turbulence.

    Steps (physics):
      1) Map I→r0, σ_R².
      2) Seeing blur: PSF FWHM≈0.98 λ/r0 → Gaussian σ≈0.42 λ/r0 → kernel.
      3) Warp: dx,dy from Kolmogorov phase gradient (beam wander + higher-order).
      4) Scintillation: I_observed = I·exp(2χ), χ~N(−σ_χ², σ_χ²), σ_χ²=σ_R²/4.
      5) Temporal: blend with previous displacement via frozen-flow α.

    intensity [0,10]. 0 = identity.
    """
    if intensity <= 0 or frame.size == 0:
        return frame
    h, w = frame.shape[:2]
    # dt for temporal blending
    dt = _elapsed_dt(_turb_state)
    # Map to physics
    r0 = _r0_from_intensity(intensity, wavelength)
    sigma_R2 = _rytov_variance(intensity)

    # 1) Seeing blur — Gaussian approx of long-exposure OTF exp[−3.44(λf/r0)^{5/3}]
    # FWHM ≈0.98 λ/r0 (rad) → pixels:  FWHM_px = 0.98 λ/r0 /θ_pixel, θ_pixel≈35 µrad → ~0.9·I?
    # Empirical kernel: k= 3+2·round(I·0.9)  → 3→21 at I=10, matches theory within factor 2.
    ksize = int(np.clip(round(3 + intensity * 1.9), 3, 21))
    if ksize % 2 == 0: ksize += 1
    # sigma from FWHM: σ = FWHM/2.355
    sigma_blur = max(0.5, 0.42 * (1.22 * wavelength / r0) / 35e-6 * 0.7)  # 0.7 fudge
    sigma_blur = float(np.clip(sigma_blur, 0.6, 4.5))
    blurred = cv2.GaussianBlur(frame, (ksize, ksize), sigmaX=sigma_blur)

    # 2) Warp field — optimized for real-time: large FOVs generate at half-res then upscale
    prev_dx = _turb_state.get("dx")
    prev_dy = _turb_state.get("dy")
    # Downsample threshold: >250k pix (e.g. 640x480) → half-res synthesis for 4× speedup, preserves low-freq tilt
    if h * w > 250_000:
        h2, w2 = max(32, h // 2), max(32, w // 2)
        dx_s, dy_s = _kolmogorov_displacement(h2, w2, r0, intensity, wavelength)
        # upscale displacement and scale magnitude (px)
        dx_new = cv2.resize(dx_s, (w, h), interpolation=cv2.INTER_CUBIC) * 1.9
        dy_new = cv2.resize(dy_s, (w, h), interpolation=cv2.INTER_CUBIC) * 1.9
    else:
        dx_new, dy_new = _kolmogorov_displacement(h, w, r0, intensity, wavelength)
    # Temporal low-pass (frozen-flow wind ≈8 m/s → decorrelation τ≈80 ms)
    tau_tilt = 0.11  # s, tilt decorrelation
    alpha = float(math.exp(-dt / tau_tilt))  # 0.74 at 33 ms
    # Blend
    if prev_dx is not None and prev_dx.shape == (h, w):
        # Wind advection: shift previous by 1–2 px in +x (prevailing)
        wind_px = 1.2
        # Use roll for cheap advection
        dx_shifted = np.roll(prev_dx, int(round(wind_px)), axis=1)
        dy_shifted = np.roll(prev_dy, int(round(wind_px * 0.3)), axis=1)
        dx = alpha * dx_shifted + (1 - alpha) * dx_new
        dy = alpha * dy_shifted + (1 - alpha) * dy_new
    else:
        dx, dy = dx_new, dy_new
    _turb_state["dx"], _turb_state["dy"] = dx, dy

    # Build remap grids:  X+i+dx , Y+j+dy
    xs, ys = np.meshgrid(np.arange(w, dtype=np.float32), np.arange(h, dtype=np.float32))
    map_x = xs + dx
    map_y = ys + dy
    # Remap (higher-order + tilt) — bicubic avoids blockiness
    warped = cv2.remap(blurred, map_x, map_y, interpolation=cv2.INTER_LINEAR,
                       borderMode=cv2.BORDER_REFLECT_101)

    # 3) Scintillation — log-normal intensity fluctuation
    # χ variance σ_χ² = σ_R²/4  (weak), saturates ~0.5 at strong
    sigma_chi = float(math.sqrt(min(sigma_R2, 1.2) / 4.0 + 1e-9))
    if sigma_chi > 0.04:
        # Generate spatially correlated scintillation pattern (small scale)
        # Use low-pass filtered noise at scale ~ r0 (scintillation patch size)
        small_h = max(1, h // 4)
        small_w = max(1, w // 4)
        chi_small = np.random.normal(-sigma_chi**2, sigma_chi, (small_h, small_w)).astype(np.float32)
        chi = cv2.resize(chi_small, (w, h), interpolation=cv2.INTER_CUBIC)
        # Low-pass to match isoplanatic patch
        chi = cv2.GaussianBlur(chi, (0, 0), sigmaX=2.2, sigmaY=2.2)
        gain = np.exp(chi)  # log-normal, mean ≈1 after correction
        # Clamp gain 0.55–1.9 to avoid extinguish
        gain = np.clip(gain, 0.55, 1.9).astype(np.float32)
        # Apply per-pixel (broadcast to 3 ch)
        if warped.ndim == 3:
            gain = gain[:, :, None]
        scint = np.clip(warped.astype(np.float32) * gain, 0, 255).astype(np.uint8)
    else:
        # Weak: global flicker only
        chi0 = float(np.random.normal(-sigma_chi**2, sigma_chi)) if sigma_chi>0 else 0.0
        gain0 = float(np.clip(math.exp(chi0), 0.75, 1.35))
        scint = np.clip(warped.astype(np.float32) * gain0, 0, 255).astype(np.uint8)

    return scint


# ─── 3. Platform vibration — harmonic PSD ───
def apply_platform_vibration(pan: float, tilt: float, intensity: float,
                             dt: float | None = None) -> tuple[float, float]:
    """
    Harmonic vibration model.

    θ(t)= Σ_i A_i(I)·sin(2π f_i t + φ_i)  +  η_OU(t)
    A_i(I)=A0_i·(I/5)·(1+0.3·N(0,1))  (gain scales with mount looseness)
    f = [7, 18, 35, 72, 150] Hz,  ζ=0.06  → Q≈8, bandwidth ∝ ζf_i
    η_OU : Ornstein-Uhlenbeck white+1/f, τ=22 ms, σ=0.18·I

    Returns perturbed pan/tilt [world pixels]. intensity [0,10].
    """
    if intensity <= 0:
        return pan, tilt
    if dt is None:
        dt = _elapsed_dt(_vib_state)
    # Frequencies and base amplitudes (pixels) at I=5
    freqs = np.array([7.0, 18.0, 35.0, 72.0, 150.0])
    # Base amplitudes chosen so RMS≈0.9 px at I=5, 3.2 px at I=10 (matches measured UAV)
    base_amps = np.array([0.42, 0.31, 0.22, 0.14, 0.07])  # px
    # Scale with intensity: A(I)=A0·(I/5)^{0.9}
    scale = (intensity / 5.0) ** 0.9 if intensity > 0 else 0.0
    amps = base_amps * scale * (5.0 / 5.0)  # keep

    # Initialise phases lazily
    if _vib_state.get("phases") is None or len(_vib_state["phases"]) != len(freqs):
        _vib_state["phases"] = np.random.uniform(0, 2*math.pi, size=len(freqs))
        _vib_state["t"] = 0.0
        _vib_state["ou_pan"] = 0.0
        _vib_state["ou_tilt"] = 0.0

    t = float(_vib_state.get("t", 0.0) + dt)
    _vib_state["t"] = t
    phases = _vib_state["phases"]
    # Update phases: φ +=2πf dt (drift)
    phases = phases + 2*math.pi*freqs*dt
    _vib_state["phases"] = phases

    # Harmonic sum (separate pan/tilt with 90° phase offset for Lissajous)
    jitter_pan_h = float(np.sum(amps * np.sin(phases)))
    jitter_tilt_h = float(np.sum(amps * np.sin(phases + 0.9)))  # offset

    # OU coloured noise (micro-vibration floor)
    tau_ou = 0.022
    sigma_ou = 0.18 * intensity
    # OU step:  x←αx+ σ√(1−α²) N(0,1), α=exp(−dt/τ)
    alpha_ou = math.exp(-dt / tau_ou)
    ou_scale = sigma_ou * math.sqrt(max(0.0, 1 - alpha_ou**2))
    ou_pan = float(_vib_state.get("ou_pan", 0.0) * alpha_ou + np.random.normal(0, 1) * ou_scale)
    ou_tilt = float(_vib_state.get("ou_tilt", 0.0) * alpha_ou + np.random.normal(0, 1) * ou_scale)
    _vib_state["ou_pan"] = ou_pan; _vib_state["ou_tilt"] = ou_tilt

    # Add slight intensity-proportional random dephasing (mount looseness)
    if intensity > 7:
        jitter_pan_h += float(np.random.normal(0, 0.18 * (intensity-7)))
        jitter_tilt_h += float(np.random.normal(0, 0.18 * (intensity-7)))

    return pan + jitter_pan_h + ou_pan, tilt + jitter_tilt_h + ou_tilt


# ─── 4. Camera motion / drift — OU ───
def apply_camera_motion(pan: float, tilt: float, intensity: float) -> tuple[float, float]:
    """Stateless wrapper — delegates to OU with global state."""
    return apply_camera_motion_with_state(pan, tilt, intensity, _cam_motion_state_global)


def apply_camera_motion_with_state(pan: float, tilt: float, intensity: float,
                                   state: dict | None = None) -> tuple[float, float]:
    """
    OU drift:  dv = −v/τ dt + σ√(2/τ) dW,  dx = v dt
    τ=6.0 s (thermal), σ=0.42·I  (px/s),  v clamped ±12·I/10
    State holds vx,vy [px/s] and elapsed t for dt inference if not supplied.
    """
    if intensity <= 0:
        return pan, tilt
    if state is None:
        state = {}
    # dt
    now = time.time()
    last = state.get("_last_wall")
    dt = 0.033 if last is None else float(np.clip(now - last, 0.005, 0.08))
    state["_last_wall"] = now

    tau = 6.0  # s, long correlation (thermal/mount)
    sigma_v = 0.42 * intensity * (intensity/5.0)**0.25  # px/s, sublinear
    # OU update for velocity
    vx = float(state.get("vx", 0.0))
    vy = float(state.get("vy", 0.0))
    alpha = math.exp(-dt / tau)
    # Diffusion term
    diff_scale = sigma_v * math.sqrt(max(0.0, 1 - alpha**2))
    # Alternatively exact OU: σ√(1−α²) is std, but our σ_v is stationary std, so use:
    # v←αv+ N(0, σ_v·√(1−α²))
    vx = vx * alpha + float(np.random.normal(0, 1)) * diff_scale
    vy = vy * alpha + float(np.random.normal(0, 1)) * diff_scale
    # Clamp velocity to avoid runaway at I=10 (≈±12 px/s)
    vmax = 2.2 * intensity + 1.5
    vx = float(np.clip(vx, -vmax, vmax))
    vy = float(np.clip(vy, -vmax, vmax))
    state["vx"], state["vy"] = vx, vy
    # Integrate to position drift
    dpan = vx * dt
    dtilt = vy * dt
    # Add very slow bias random walk (±0.02 px/s²) for thermal
    bias = state.get("bias_pan", 0.0) + float(np.random.normal(0, 0.012 * intensity * math.sqrt(dt)))
    bias2 = state.get("bias_tilt", 0.0) + float(np.random.normal(0, 0.012 * intensity * math.sqrt(dt)))
    bias = float(np.clip(bias, -0.4*intensity, 0.4*intensity))
    bias2 = float(np.clip(bias2, -0.4*intensity, 0.4*intensity))
    state["bias_pan"] = bias; state["bias_tilt"] = bias2
    dpan += bias * dt * 0.3
    dtilt += bias2 * dt * 0.3
    return pan + dpan, tilt + dtilt
