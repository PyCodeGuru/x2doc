# x2doc Stage 1 Closeout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close stage one with Chinese structure/golden coverage, deterministic Shanghai timestamps, local-media CLI integration coverage, and a read-only network probe.

**Architecture:** Keep the synchronous conversion pipeline unchanged. Extend only frozen fixtures/tests, pure parser/renderer rules, clock injection at the application boundary, and a standalone diagnostic script that never participates in fetching.

**Tech Stack:** Python 3.11+, pytest, pytest-httpx/local HTTP server, Pydantic, Typer, httpx, Playwright, Ruff.

---

### Task 1: Freeze the Chinese long-text fixture and Markdown contract

**Files:**
- Create: `tests/fixtures/syndication/chinese_long_text.json`
- Create: `tests/fixtures/syndication/chinese_long_text.meta.json`
- Create: `tests/golden/chinese_long_text.md`
- Modify: `tests/test_tweet_json.py`
- Modify: `tests/test_markdown.py`

- [ ] Add a frozen payload containing standalone bold heading, bullet/ordered lists, fenced code, literal ``~/.claude/settings.json``, divider, two expanded t.co URLs, and one hashtag.
- [ ] Write parser and golden assertions for the exact block sequence, both long URLs, code indentation, and front-matter tags.
- [ ] Run `pytest tests/test_tweet_json.py tests/test_markdown.py -q`; expect RED for the new Markdown/time/title contract before production changes.

### Task 2: Freeze title, slug, timestamp, and front-matter corrections

**Files:**
- Create: `tests/fixtures/syndication/chinese_title.json`
- Create: `tests/fixtures/syndication/symbol_title.json`
- Modify: `tests/test_tweet_json.py`
- Modify: `tests/test_app.py`
- Modify: `tests/test_markdown.py`

- [ ] Assert derived titles omit terminal punctuation.
- [ ] Assert Chinese slug preservation and symbol/emoji fallback to `tweet-<id>` using parsed fixtures, not post-parse mutation.
- [ ] Assert existing output without overwrite raises before any output mutation.
- [ ] Assert `fetched_at` is Shanghai, `published_at_utc/schema_version/fetch_path` exist, metrics do not, and the source footer uses two independent quote lines.

### Task 3: Implement minimal parser/renderer/application changes

**Files:**
- Modify: `src/x2doc/parsers/tweet_json.py`
- Modify: `src/x2doc/renderers/markdown.py`
- Modify: `src/x2doc/app.py`
- Modify: `src/x2doc/fetchers/syndication.py`
- Modify: `src/x2doc/cache.py`

- [ ] Strip exactly one derived terminal sentence punctuation mark without changing body text.
- [ ] Normalize real fetch times at the fetch/application boundary to `Asia/Shanghai`; accept `clock: Callable[[], datetime]` for deterministic tests.
- [ ] Render the revised front matter and two-line source block without metrics.
- [ ] Run targeted tests and confirm GREEN.

### Task 4: Add a real CLI-to-local-HTTP media integration test

**Files:**
- Create: `tests/test_cli_media_e2e.py`

- [ ] Start a local threaded HTTP stub with success, duplicate-content, and failure routes.
- [ ] Seed the standard cache with a document whose media URLs point only at the stub.
- [ ] Invoke the real Typer CLI with `--images local` and isolated output/cache environment.
- [ ] Assert one hash-named file for duplicate bytes, relative Markdown references, remote fallback, and visible warning.
- [ ] Run the new test; expect RED until any necessary cache/CLI injection seam is implemented, then GREEN.

### Task 5: Refresh golden tooling and full stage-one verification

**Files:**
- Modify: `scripts/update_golden.py`
- Modify: `README.md`

- [ ] Make golden time deterministic through an injected/frozen clock value, never renderer constants.
- [ ] Run `pytest -q`; expect every non-network test to pass.
- [ ] Run `ruff check .`; expect exit 0.
- [ ] Generate and retain a complete Chinese long-text `index.md` review artifact.

### Task 6: Build the read-only network probe

**Files:**
- Create: `scripts/probe_network.py`
- Create: `tests/test_probe_network.py`

- [ ] Write offline tests for per-stage DNS/TCP/TLS/HTTP result recording and table formatting.
- [ ] Implement one timed request per requested host plus one Playwright Chromium visit to `https://x.com/robots.txt`.
- [ ] Ensure the script prints measurements only and does not alter fetch configuration or use proxies.
- [ ] Run targeted tests and Ruff.

### Task 7: Run and report the probe

- [ ] Execute `python scripts/probe_network.py` once with bounded timeouts.
- [ ] Preserve the exact output for user review without solution inference.
- [ ] Commit the closeout changes and stop before Article/thread work.
