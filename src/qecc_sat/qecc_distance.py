"""Compatibility facade for QECC distance algorithms.

New code may import from ``qecc_sat.distance`` modules directly. This module
preserves the historical ``qecc_sat.qecc_distance`` API.
"""

from __future__ import annotations

from .distance import (
    STABILIZER_5QUBIT_SYMPLECTIC,
    STABILIZER_SURFACE_5_1_2,
    STABILIZER_SURFACE_81_1_9,
    _symp,
    css_logical_nbit_rows,
    logical_basis_css_from_parity_checks,
    logical_basis_symplectic,
    min_distance_parity_check,
    min_distance_quantum_css_split_minmax,
    min_distance_quantum_css_split_or_logicals,
    min_distance_quantum_minmax_auto,
    min_distance_quantum_minmax_or_logicals,
    min_distance_quantum_stabilizer,
    min_distance_quantum_stabilizer_blocking,
    min_distance_quantum_stabilizer_card_refine,
    min_distance_quantum_stabilizer_or_logicals,
    min_distance_quantum_stabilizer_stepwise_card,
    min_distance_with_witness,
    pretty_print_stabilizer,
    rotated_surface_code_stabilizers,
    split_css_stabilizers,
    stabilizer_to_pauli_coords,
    stabilizer_to_pauli_string,
    symplectic_from_css_nbit_rows,
)

__all__ = [
    "STABILIZER_5QUBIT_SYMPLECTIC",
    "STABILIZER_SURFACE_5_1_2",
    "STABILIZER_SURFACE_81_1_9",
    "_symp",
    "css_logical_nbit_rows",
    "logical_basis_css_from_parity_checks",
    "logical_basis_symplectic",
    "min_distance_parity_check",
    "min_distance_quantum_css_split_minmax",
    "min_distance_quantum_css_split_or_logicals",
    "min_distance_quantum_minmax_auto",
    "min_distance_quantum_minmax_or_logicals",
    "min_distance_quantum_stabilizer",
    "min_distance_quantum_stabilizer_blocking",
    "min_distance_quantum_stabilizer_card_refine",
    "min_distance_quantum_stabilizer_or_logicals",
    "min_distance_quantum_stabilizer_stepwise_card",
    "min_distance_with_witness",
    "pretty_print_stabilizer",
    "rotated_surface_code_stabilizers",
    "split_css_stabilizers",
    "stabilizer_to_pauli_coords",
    "stabilizer_to_pauli_string",
    "symplectic_from_css_nbit_rows",
]
