# x2doc Doctor and User Guide Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a returning user diagnose the local environment and convert one X link to Markdown/PDF without remembering project setup.

**Architecture:** Keep environment checks in `doctor.py` as nine independent injectable functions returning display-ready results. Preserve `x2doc URL` by using a default-command Typer group that inserts the internal `convert` command unless the user explicitly asks for `doctor`. Keep the shell wrapper limited to venv bootstrap, local proxy detection, one URL prompt, and the recommended conversion command.

**Tech Stack:** Python 3.11, Typer, httpx, Playwright, pytest, zsh/bash, Markdown.

---

### Task 1: Doctor contracts

**Files:** `tests/test_doctor.py`, `src/x2doc/doctor.py`

- [ ] Add failing tests proving all nine injected checks run even after failures, successful summary exits 0, failed summary exits 4, proxy credentials are redacted, and size formatting is deterministic.
- [ ] Implement `DoctorCheck`, individual check functions, and `run_doctor()` with no short-circuiting.
- [ ] Run `pytest tests/test_doctor.py -q` and Ruff until green.

### Task 2: Backward-compatible CLI

**Files:** `tests/test_cli.py`, `src/x2doc/cli.py`

- [ ] Add failing CLI tests for `x2doc doctor`, failed doctor exit 4, unchanged `x2doc URL`, and no-argument exit 1.
- [ ] Add a default-command `TyperGroup`, expose internal `convert` plus `doctor`, and keep direct URL invocation unchanged.
- [ ] Run focused and full offline tests.

### Task 3: Wrapper and documentation

**Files:** `.gitignore`, `scripts/x2doc-run.sh`, `docs/使用指南.md`, `README.md`

- [ ] Ignore `.DS_Store`, cookie exports, and private cookie directories.
- [ ] Add a wrapper that starts at the project root, creates/repairs `.venv`, detects local port 7892, prompts for one URL, and runs recommended Markdown/PDF conversion.
- [ ] Write the guide with exactly the eight requested top-level headings and only executable instructions.
- [ ] Add the README five-minute block with three commands and the full-guide link.

### Task 4: Fresh-shell acceptance

**Files:** temporary validation directory outside the repository

- [ ] In a new shell, move the existing `.venv` aside recoverably, create a fresh `.venv`, install editable dependencies, and install Chromium.
- [ ] Run `x2doc doctor` through `http://127.0.0.1:7892` and require all nine checks to pass.
- [ ] Run the supplied target to Markdown/PDF/local images and record complete output.
- [ ] Record GitHub URL exit 1, unreachable proxy exit 3, and existing-output exit 1.
- [ ] Run fresh `pytest -q`, `ruff check .`, verify the guide commands against actual output, commit once, and leave the worktree clean.
