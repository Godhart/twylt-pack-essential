# ADR 0002 — essential 0.2.0 shared runtime

Accepted, 2026-10-07. Supersedes ADR 0001 paragraph 2 and copied policy in paragraph 5.
Guardrails are imported from TWYLT 1.1.0. Individual tools contain their contracts
and own logic. HTTP common to curl/wget/search is an installed pack module, never
embedded wholesale. ContractModel replaces repeated strict model configuration.
Tools remain source entrypoints; builder's path-based launcher is compatible.
Tradeoff: shared modules must be installed in the runtime before launching tools.
No aggregated production common.py is retained. Tests may aggregate for regressions.
