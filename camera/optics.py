"""
Module: camera.optics
Purpose: Optics helpers — pixel ↔ angle conversions for reporting.
Public API: pixel_to_mrad, pixel_to_urad, mrad_to_pixel
Notes: Stateless, used by CameraConfig, PTZCamera, and Dashboard reporting.
       Real FSOC systems quote error in mrad/µrad; this bridges simulation px to angular units.
"""

# ============================================================
# SECTION: Pixel ↔ Angle conversions
# ============================================================

def pixel_to_mrad(px: float, scale_mrad_per_px: float = 0.035) -> float:
    """
    Convert pixel error to milliradians.

    scale_mrad_per_px : mrad per px (e.g., 0.035 mrad/px = 35 µrad). Comes from
                        CameraConfig.pixel_scale_mrad, configurable in Camera panel Units.
    """
    return float(px) * float(scale_mrad_per_px)

def pixel_to_urad(px: float, scale_mrad_per_px: float = 0.035) -> float:
    """Convert pixel error to microradians (1 mrad = 1000 µrad)."""
    return pixel_to_mrad(px, scale_mrad_per_px) * 1000.0

def mrad_to_pixel(mrad: float, scale_mrad_per_px: float = 0.035) -> float:
    """Inverse: mrad → px."""
    s = float(scale_mrad_per_px)
    if s <= 1e-9:
        return 0.0
    return float(mrad) / s

def format_angular_error(px: float, scale_mrad_per_px: float = 0.035) -> str:
    """
    Human-readable angular error for dashboard/footer.

    Returns e.g., "12.3 px (0.43 mrad / 430 µrad)".
    """
    mrad = pixel_to_mrad(px, scale_mrad_per_px)
    urad = mrad * 1000.0
    return f"{px:.1f} px ({mrad:.3f} mrad / {urad:.0f} µrad)"
