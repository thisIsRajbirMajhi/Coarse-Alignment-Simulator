# perf_log/rates.py - Isolated detection/hit rates — split from PerformanceLogger

def compute_rates(frame_count: int, detection_count: int, hitbox_hit_count: int, center_hit_count: int) -> dict:
    total = frame_count if frame_count else 1
    lock_retention = 0.0  # caller fills
    detection_rate = (detection_count / frame_count * 100) if frame_count else 0.0
    hitbox_rate = (hitbox_hit_count / detection_count * 100) if detection_count else 0.0
    center_rate = (center_hit_count / hitbox_hit_count * 100) if hitbox_hit_count else 0.0
    center_overall = (center_hit_count / detection_count * 100) if detection_count else 0.0
    center_hit_rate = (center_hit_count / total * 100) if frame_count else 0.0
    return {
        "detection_rate": detection_rate,
        "hitbox_rate": hitbox_rate,
        "center_rate": center_rate,
        "center_overall": center_overall,
        "center_hit_rate": center_hit_rate,
    }