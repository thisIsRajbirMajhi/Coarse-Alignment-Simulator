"""Deprecated alias — use disturbance.environment.atmospheric directly.

Strict-compat shim: the optical channel's beam-state physics lives in
disturbance.optical.channel (authoritative); this image-space helper is only
the background-residual rendering. Kept for legacy imports.
"""
from disturbance.environment.atmospheric import apply_atmospheric_disturbance


def apply_atmospheric_propagation(frame, **kwargs):
    return apply_atmospheric_disturbance(frame, **kwargs)


__all__ = ["apply_atmospheric_propagation"]