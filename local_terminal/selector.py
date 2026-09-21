# local_terminal/selector.py - V2 active-target selection (Plan V2 §16).
#
# One active PTZ target. Simple priority:
#   1. mission priority TID (if configured)
#   2. strongest P_rx
#   3. highest SNR
# No composite score, no standby pool, no Hungarian.

from __future__ import annotations


def select_active_v2(candidates, policy: str = "priority",
                     priority_order: list[str] | None = None) -> str | None:
    """Choose one active TID from validated candidates.

    Args:
        candidates: iterable of TargetObservation/BeaconObservation/dicts with
            terminal_id/tid, p_rx_w, snr_db attributes.
        policy: 'priority' | 'strongest_prx' | 'highest_snr'.
        priority_order: mission priority TID list, index 0 = highest.
    Returns TID or None.
    """
    cands = list(candidates or [])
    if not cands:
        return None

    def _tid(c):
        if isinstance(c, dict):
            return str(c.get("terminal_id") or c.get("tid") or "")
        return str(getattr(c, "terminal_id", "") or getattr(c, "tid", "") or "")

    def _prx(c):
        if isinstance(c, dict):
            return float(c.get("p_rx_w", 0.0) or 0.0)
        return float(getattr(c, "p_rx_w", 0.0) or 0.0)

    def _snr(c):
        if isinstance(c, dict):
            return float(c.get("snr_db", 0.0) or 0.0)
        return float(getattr(c, "snr_db", 0.0) or 0.0)

    valid = [c for c in cands if _tid(c)]
    if not valid:
        return None
    policy = str(policy or "priority").lower()
    if policy == "priority" and priority_order:
        order = {str(t): i for i, t in enumerate(priority_order)}
        ranked = sorted(valid, key=lambda c: (order.get(_tid(c), 10**9), -_prx(c), -_snr(c)))
        return _tid(ranked[0])
    if policy == "strongest_prx":
        return _tid(max(valid, key=lambda c: (_prx(c), _snr(c))))
    if policy == "highest_snr":
        return _tid(max(valid, key=lambda c: (_snr(c), _prx(c))))
    if priority_order:
        return select_active_v2(valid, "priority", priority_order)
    return select_active_v2(valid, "strongest_prx")


__all__ = ["select_active_v2"]
