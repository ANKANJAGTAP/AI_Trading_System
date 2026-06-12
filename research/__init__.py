"""Research layer (Phase 4): meta-labeling on the audit trail.

Builds a labeled dataset (gate features -> trade won/lost) from signals/gate_results/
positions, trains a TRANSPARENT model (logistic regression in numpy — coefficients
are inspectable, no black box), and exposes it as an opt-in confidence FILTER in the
orchestrator. It can only downsize/skip a trade the deterministic funnel already
approved — never originate one. Off by default until trained AND validated.
"""
