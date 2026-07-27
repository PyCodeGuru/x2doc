# WeChat Platform Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add WeChat public-article conversion without changing existing X semantics.

**Architecture:** Introduce an internal platform registry around a shared canonical target and document pipeline. Keep platform-specific URL, fetcher, parser, cache and naming policies isolated while reusing media and renderers.

**Tech Stack:** Python 3.11+, Typer, httpx, BeautifulSoup, Playwright, Pydantic, pytest.

---

### Task 1: Platform registry and X adapter

**Files:** create `src/x2doc/platforms/{__init__,base,x}.py`; modify `routing.py`, `app.py`, `models.py`; test `tests/test_platforms.py` and existing routing/app/markdown tests.

- [ ] Write failing tests for X `CanonicalTarget`, unsupported-platform diagnostics, enum front matter and `output/x` naming.
- [ ] Run focused tests and verify expected failures.
- [ ] Implement registry and route compatibility alias; route app through the registry.
- [ ] Run focused and complete tests.

### Task 2: Cache v2, output migration and network policy

**Files:** modify `cache.py`, `network.py`, `cli.py`; create `scripts/migrate_output.py`; test `test_cache.py`, `test_network.py`, `test_migrate_output.py`.

- [ ] Write failing v1 fixture migration, dry-run/apply/conflict, domain bypass and CLI option tests.
- [ ] Verify RED; implement v2 paths/envelope/offline migration, migration script and repeatable domain parsing.
- [ ] Verify GREEN, run X golden diff and offline cache render.
- [ ] Commit `refactor: platformize x2doc without changing x behavior`.

### Task 3: WeChat URL and fetchers

**Files:** create `platforms/wechat.py`, `fetchers/wechat.py`; modify pipeline/app/errors; create error HTML fixtures; test `test_wechat_platform.py`, `test_wechat_fetcher.py`.

- [ ] Write failing tests for both URL forms, tracking removal, original URL preservation, static/playwright fallback and four error classes.
- [ ] Verify RED; implement canonicalization, static fetcher and Playwright fallback with direct network policy.
- [ ] Verify GREEN.

### Task 4: WeChat parser and media

**Files:** create `parsers/wechat_dom.py` and four fixture/golden groups; modify `models.py`, `media.py`, `renderers/markdown.py`; test `test_wechat_dom.py`, media tests.

- [ ] Write fixture-backed failing snapshot tests for metadata, headings, lists, code, quote, table, images, divider and placeholders.
- [ ] Write failing tests for data-src order, Referer, wx_fmt/content-type extension and GIF handling.
- [ ] Verify RED; implement minimal recursive parser and media policy.
- [ ] Update goldens from reviewed deterministic output; verify GREEN and all X tests.
- [ ] Commit `feat: add wechat public article conversion`.

### Task 5: Doctor, docs and final acceptance

**Files:** modify `doctor.py`, `docs/使用指南.md`, `README.md`, `scripts/x2doc-run.sh` and tests.

- [ ] Write failing doctor and wrapper wording tests; implement two WeChat checks and network-route display.
- [ ] Update user docs and README with WeChat commands, errors, output layout and migration.
- [ ] Run full pytest and Ruff.
- [ ] Run real WeChat and X conversions, PDF extraction, cache-offline rerenders, path/error checks and X baseline diff.
- [ ] Commit `docs: complete dual-platform guidance and checks`, merge to main, push and verify remote SHA.
