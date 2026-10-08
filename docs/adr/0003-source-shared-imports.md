# ADR 0003 — essential 0.3.0: shared source imports

Accepted, 2026-10-08. Supersedes ADR 0002's installed shared-module decision.

The pack is deployed as source files, without building or installing a Python
package. curl, wget and web_search insert the pack's shared directory into sys.path,
computed from Path(__file__).resolve().parents[2]. They import essential_common.http.
Only these three tools need this import. echo, sleep and ping remain independent.
Guardrails remain in the installed TWYLT library; HTTP business logic has one source.

The short repeated import-path setup is intentional: each tool must work when
loaded directly by builder or runpy, without bootstrap setup or cwd assumptions.
There is no pack-wide registry or business-logic aggregation in production.

Deploy the entire tools/shared tree and install requirements.txt. Builder still
references original source paths; copying only its generated toolpack is insufficient.
Remove obsolete essential package pins from image/host dependency configurations.
The shared directory must be trusted. A distinct module name reduces collisions;
Python's module cache means different pack versions need separate processes.
No import sandbox is provided. Arbitrary tool filesystem access remains subject to
OS permissions and the tool author's use of TWYLT's cooperative checks.

Version 0.3.0 marks the deployment/layout change. Tool schemas and few-shots remain
compatible; tool requirements and implementation versions change.
