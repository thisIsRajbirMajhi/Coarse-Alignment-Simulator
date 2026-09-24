# local_terminal/selector.py - V2 active-target selection (Plan Hybrid-AI §2).
#
# Priority only (strongest_prx/highest_snr removed — duplicate of identity).
# Single policy: mission priority → strongest P_rx.

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
    # Pruned: only priority policy kept (Plan Hybrid-AI). Other policies alias to priority.
    if priority_order:
        order = {str(t): i for i, t in enumerate(priority_order)}
        ranked = sorted(valid, key=lambda c: (order.get(_tid(c), 10**9), -_prx(c), -_snr(c)))
        return _tid(ranked[0])
    return _tid(max(valid, key=lambda c: (_prx(c), _snr(c))))


__all__ = ["select_active_v2"]
