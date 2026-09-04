# camera/optics.py - Optics helpers — pixel ↔ angle conversions for reporting

def pixel_to_mrad(px: float, scale_mrad_per_px: float = 0.035) -> float:
    """
    Convert pixel error to milliradians.

    scale_mrad_per_px : mrad per px (e.g., 0.109 mrad/px = 109 µrad for 640x480 4°×3°). Comes from
                         CameraConfig.pixel_scale_mrad, configurable in Camera panel Units.
    For non-square FOV, use pixel_to_mrad_xy with separate x/y scales.
    """
    return float(px) * float(scale_mrad_per_px)

def pixel_to_mrad_xy(px_x: float, px_y: float, scale_x: float = 0.109, scale_y: float = 0.109) -> tuple[float, float]:
    """Convert separate px errors to mrad using x/y scales (for anamorphic FOV)."""
    return (float(px_x) * float(scale_x), float(px_y) * float(scale_y))

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

def format_angular_error_xy(px_x: float, px_y: float, scale_x: float = 0.109, scale_y: float = 0.109) -> str:
    """Anamorphic version with separate scales."""
    mx, my = pixel_to_mrad_xy(px_x, px_y, scale_x, scale_y)
    return f"({px_x:.1f},{px_y:.1f}) px ({mx:.3f},{my:.3f}) mrad"