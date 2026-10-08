# 0.3.0 — 2026-10-08

- Load shared HTTP code from shared/essential_common using each tool's __file__.
- Remove mandatory Python-package build/install and self-dependencies from tool requirements.
- Keep echo, sleep and ping independent of shared HTTP code.
- Preserve guardrails, contracts and existing behavioral tests; verify copied source packs and builder HTTP launchers from arbitrary cwd without an installed essential package.

# 0.2.0 — 2026-10-07

- Move guardrails to TWYLT >=1.1.0; opt-in except image defaults.
- Replace embedded whole-pack code with individual tools and one installed HTTP module.
- Replace TWYLT_ESSENTIAL_DISABLE_NETWORK with common TWYLT_DISABLE_NETWORK.
- Support nested transport cwd outside business workspace.
- Preserve schemas, examples, previous behavioral tests and add builder integration.

# Changelog

## 0.1.1

Добавлена команда `echo`: точный возврат строки `text`; standalone-инструмент, схемы, примеры и тесты.

## 0.1.0

Первый выпуск: sleep, wget, curl, ICMP ping, поиск SearXNG; автономные инструменты TWYLT 1, workspace-политика файлового пака, схемы и регрессионные тесты.
