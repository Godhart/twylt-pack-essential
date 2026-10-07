# Testing twylt-pack-essential 0.2.0

Python 3.12 preparation: 20 tests passed (17 previous behavioral tests + 3 integration).
Local HTTP server and mocked ping; external SearXNG and real ICMP not exercised.
Builder 0.4.1 scan finds all six tools and its actual generated launcher runs echo
from a nested cwd outside workspace, using input.json/output.json and closed stdin.

Install TWYLT 1.1.0 and this source first, then optionally builder for integration:

```bash
python -m pip install ../twylt-1.1.0 . toolpack-builder==0.4.1
python -m unittest discover -s tests -v
python scripts/export_schemas.py
```

No external network is used by test requests. The module must also be installed
in subprocess interpreters. Wheels are provided in dist; install them with pip
when the new versions are not yet published. Generated schemas are refreshed.
