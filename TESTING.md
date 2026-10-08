# Testing twylt-pack-essential 0.3.0

## Results

Python 3.12: 22 tests passed (17 preserved behavioral tests, 3 existing integration
tests, 2 new source-deployment tests). Also passed in an isolated venv containing
TWYLT 1.1.0, Pydantic 2.13.5 and builder 0.4.1, with no installed essential package.
Dependencies for that venv were provisioned offline from the available TWYLT wheel
and installed external dependency files; pip check reported no broken requirements.
The attempted online setup could not reach the builder package index.

The new deployment test copies only tools/ and shared/ to another location,
rejects imports of the old installed pack via sitecustomize, and exercises curl's
actual HTTP business logic through tool.py, run.py and builder's generated launcher.
The launcher uses closed stdin and input.json/output.json in a nested cwd outside
workspace. Builder discovers all six tools; HTTP tool requirements have no self-pin.
Separate subprocess checks confirm echo, sleep and ping do not import shared HTTP.

Local HTTP server and mocked ping only; external SearXNG and real ICMP not exercised.
HTTP implementation bytes, input/output schemas and few-shots match GitHub 0.2.0.
Implementation versions and requirements were intentionally updated.

## Reproduce

Install TWYLT >=1.1.0 first from source or wheel if not yet in your package index.
Install only external dependencies; do not install or build this source pack.
Builder 0.4.1 is required for integration tests; install its source checkout if
unavailable in your package index.

```bash
python -m pip install -r requirements.txt
python -m pip install /path/to/toolpack-builder-0.4.1
python -m unittest discover -s tests -v
python scripts/export_schemas.py
```

Keep tools/ and shared/ together. No PYTHONPATH configuration is needed at runtime.

## Source provenance

Based on the latest GitHub main checked on 2026-10-08:
https://github.com/Godhart/twylt-pack-essential
commit 488e1a78f0400161884cd8034409b9d733880394 (version 0.2.0).
The archive includes a patch against that commit and SHA256SUMS.
