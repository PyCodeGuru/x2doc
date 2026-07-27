# x2doc Mobile Publisher Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a deterministic mobile-triggered publisher that converts one supported URL to Markdown/PDF in an isolated worktree and pushes only that output to `PyCodeGuru/x2doc`.

**Architecture:** A thin shell entry invokes a testable Python orchestrator. The orchestrator validates identity and repository boundaries, maintains a persistent publishing worktree, runs x2doc, stages exactly one output directory, pushes one commit, and emits JSON. A concise personal Codex skill maps natural-language mobile requests to the fixed entry point.

**Tech Stack:** Python 3.11+, subprocess, pathlib, Git worktrees, Bash, pytest, Codex Agent Skills.

---

### Task 1: Publisher contract and safety core

**Files:**
- Create: `scripts/x2doc_publish.py`
- Create: `tests/test_x2doc_publish.py`

- [ ] **Step 1: Write failing tests for URL validation, identity validation, and output containment**

Create tests that import `PublishError`, `validate_source_url`, `validate_identity`, and `validate_output_dir`. Assert X and WeChat URLs pass; GitHub URLs, wrong GitHub login, wrong remote, absolute external paths, and traversal paths fail with the documented exit codes.

- [ ] **Step 2: Run tests and verify RED**

Run: `PYTHONPATH=src /Users/paipai_tm/Work/tools/x2doc/.venv/bin/python -m pytest -q tests/test_x2doc_publish.py`

Expected: collection fails because `scripts.x2doc_publish` does not exist.

- [ ] **Step 3: Implement the validation core**

Implement typed configuration and errors. Reuse `x2doc.routing.resolve_target` for URL validation. Normalize the remote URL and require owner/repository `PyCodeGuru/x2doc`. Resolve output paths and require they are descendants of `<publish-worktree>/output`.

- [ ] **Step 4: Run tests and verify GREEN**

Run the Task 1 command. Expected: all Task 1 tests pass.

### Task 2: Isolated Git publication workflow

**Files:**
- Modify: `scripts/x2doc_publish.py`
- Modify: `tests/test_x2doc_publish.py`

- [ ] **Step 1: Write failing workflow tests**

Use temporary Git repositories and an injected command runner. Cover atomic lock acquisition, clean worktree requirement, fast-forward synchronization, exact output staging, rejection of out-of-scope staged paths, no-change behavior, commit creation, push failure, and JSON result fields.

- [ ] **Step 2: Run tests and verify RED**

Run the Task 1 pytest command. Expected: failures for missing publisher workflow functions.

- [ ] **Step 3: Implement the minimal workflow**

Implement `Publisher.publish(url)` with explicit argument arrays. Never use shell execution. Parse x2doc output paths, verify generated files and Markdown local image references, stage only the resolved output directory, inspect `git diff --cached --name-only -z`, commit, push `HEAD:main`, and return a serializable `PublishResult`.

- [ ] **Step 4: Run tests and verify GREEN**

Run the Task 1 pytest command. Expected: all publisher tests pass.

### Task 3: Stable shell entry and user documentation

**Files:**
- Create: `scripts/x2doc-publish.sh`
- Create: `tests/test_x2doc_publish_shell.py`
- Modify: `README.md`
- Modify: `docs/使用指南.md`

- [ ] **Step 1: Write a failing shell entry test**

Run the shell entry with zero and two URLs and assert exit code 1. Inject a fake Python publisher and assert one URL is forwarded as one argument without evaluation.

- [ ] **Step 2: Run and verify RED**

Run: `PYTHONPATH=src /Users/paipai_tm/Work/tools/x2doc/.venv/bin/python -m pytest -q tests/test_x2doc_publish_shell.py`

Expected: failure because the entry script does not exist.

- [ ] **Step 3: Implement shell entry and docs**

The shell script uses absolute project paths, sets no credentials, and `exec`s the Python orchestrator with exactly one URL. Document the iPhone sentence, success response, output location, and failure recovery commands.

- [ ] **Step 4: Run and verify GREEN**

Run both publisher test files. Expected: all tests pass.

### Task 4: Codex personal skill

**Files:**
- Create outside repository: `~/.codex/skills/x2doc-publisher/SKILL.md`
- Create outside repository: `~/.codex/skills/x2doc-publisher/agents/openai.yaml`

- [ ] **Step 1: Run a baseline pressure scenario without the skill**

Ask a fresh subagent to handle a mobile-style “convert and upload” prompt without exposing the intended workflow. Record whether it invents commands, touches the active worktree, or omits identity/staging checks.

- [ ] **Step 2: Initialize the skill with the official generator**

Run `init_skill.py x2doc-publisher --path /Users/paipai_tm/.codex/skills` with interface fields for the display name, short description, and a `$x2doc-publisher` default prompt.

- [ ] **Step 3: Write the minimal skill instructions**

Require the absolute `scripts/x2doc-publish.sh` entry, one URL, no ad-hoc Git commands, JSON verification, and a concise Chinese success/failure response.

- [ ] **Step 4: Validate and forward-test the skill**

Run `quick_validate.py`. Then ask a fresh subagent to use the skill on a dry-run scenario and verify it selects only the fixed entry point and reports required fields.

### Task 5: Full verification and live publication

**Files:**
- Generated: `output/x/yanhua1010-*/index.md`
- Generated: `output/x/yanhua1010-*/index.pdf`
- Generated: `output/x/yanhua1010-*/assets/*`

- [ ] **Step 1: Run full offline verification**

Run `PYTHONPATH=src /Users/paipai_tm/Work/tools/x2doc/.venv/bin/python -m pytest -q` and `/Users/paipai_tm/Work/tools/x2doc/.venv/bin/ruff check .`.

- [ ] **Step 2: Run the live mobile-equivalent request**

Run `/Users/paipai_tm/Work/tools/x2doc/scripts/x2doc-publish.sh 'https://x.com/yanhua1010/status/2039966047378583815'` after the feature branch is integrated so the persistent publisher starts from the new `origin/main`.

- [ ] **Step 3: Verify remote artifacts**

Use `gh api` to verify the commit belongs to `PyCodeGuru`, both `index.md` and `index.pdf` exist under the returned GitHub path, and the PDF has at least one page. Confirm the source worktree remains clean.
