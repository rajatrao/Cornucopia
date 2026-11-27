"""Deterministic resource compiler: pure functions over an OperationalSnapshot.

Nothing in this package performs I/O, reads the clock, or uses randomness;
the same snapshot and options always produce byte-identical results.
"""
