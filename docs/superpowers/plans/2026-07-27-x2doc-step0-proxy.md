# x2doc Step 0 Proxy Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make authenticated HTTP/HTTPS/SOCKS5 proxy configuration a first-class x2doc capability and produce an honest direct-versus-proxy connectivity report.

**Architecture:** Add one focused network module that resolves proxy precedence, validates and redacts proxy URLs, creates all httpx clients, and translates the selected proxy for Playwright. Pass the resolved configuration from CLI to the synchronous application service, Syndication fetcher, and asynchronous media downloader. Keep the diagnostic script independent from fetcher fallback behavior and probe each required real URL exactly once per mode.

**Tech Stack:** Python 3.11, Typer, httpx, Playwright Chromium, pytest, pytest-httpx, Ruff.

---

### Task 1: Freeze proxy configuration contracts with tests

**Files:**
- Create: `tests/test_network.py`
- Modify: `tests/test_cli.py`

- [ ] Test precedence `--proxy > X2DOC_PROXY > HTTPS_PROXY > ALL_PROXY > direct` with an injected environment mapping.
- [ ] Test supported schemes, authenticated proxy parsing, and redaction to `scheme://host:port`.
- [ ] Test invalid proxy values produce `ParameterError` without exposing credentials.
- [ ] Test the CLI forwards `--proxy` to `convert`.
- [ ] Run the focused tests and verify they fail because the network module and CLI option do not exist.

### Task 2: Implement central client factories and wire current network paths

**Files:**
- Create: `src/x2doc/network.py`
- Modify: `src/x2doc/cli.py`
- Modify: `src/x2doc/app.py`
- Modify: `src/x2doc/fetchers/syndication.py`
- Modify: `src/x2doc/media.py`
- Modify: `tests/test_syndication_fetcher.py`
- Modify: `tests/test_media.py`

- [ ] Implement `ProxyConfig`, `resolve_proxy()`, safe redaction, `build_http_client()`, `build_async_http_client()`, and `build_playwright_proxy()`.
- [ ] Keep `trust_env=True`, pass the resolved proxy explicitly, and share timeout, browser UA, redirect behavior, and proxy parsing between sync/async factories.
- [ ] Resolve proxy once in `convert()`, pass it to Syndication and media localization, and preserve dependency injection compatibility.
- [ ] Run focused tests until green, then run all offline tests.

### Task 3: Rewrite the network probe as a direct/proxy comparison

**Files:**
- Modify: `scripts/probe_network.py`
- Modify: `tests/test_probe_network.py`

- [ ] Add failing tests for required real URLs, response byte count, JSON top-level keys, direct/proxy columns, proxy redaction, and Playwright proxy settings.
- [ ] Probe DNS/TCP/TLS directly as transport stages; for the proxy column report the proxy transport stages and request each target URL once through the selected proxy.
- [ ] Use a normal Chromium UA and record HTTP status, bytes, JSON keys, and elapsed time without retries.
- [ ] Launch installed Chromium explicitly with the selected proxy for `https://x.com/robots.txt`.
- [ ] Run focused tests until green.

### Task 4: Document, install, verify, probe, and commit Step 0

**Files:**
- Modify: `README.md`

- [ ] Document proxy precedence, supported formats, authentication, examples, environment configuration, and redacted logging behavior.
- [ ] Run `.venv/bin/python -m playwright install chromium` without elevated privileges.
- [ ] Run `.venv/bin/python -m pytest -q` and `.venv/bin/python -m ruff check .`.
- [ ] Run the probe once with `--proxy http://127.0.0.1:7892`, capture complete raw stdout/stderr, and do not retry or alter assertions to hide failures.
- [ ] Review the diff for secrets, commit only Step 0, verify the worktree is clean, report raw probe output, and stop before Step 1.
