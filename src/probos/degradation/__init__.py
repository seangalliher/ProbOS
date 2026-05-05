"""Saucer Separation — Graceful Degradation (AD-459 / AD-459b)."""

from probos.degradation.subsystem import LifecycleAdapter, SheddableSubsystem

__all__ = [
    "LifecycleAdapter",
    "SheddableSubsystem",
]
