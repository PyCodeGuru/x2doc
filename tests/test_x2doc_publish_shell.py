from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

import scripts.x2doc_publish as publisher_module
from scripts.x2doc_publish import PublishError, PublishResult

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SHELL_ENTRY = PROJECT_ROOT / "scripts" / "x2doc-publish.sh"


@pytest.mark.parametrize("arguments", [[], ["https://x.com/a/status/1", "extra"]])
def test_shell_entry_requires_exactly_one_url(arguments: list[str]) -> None:
    result = subprocess.run(
        [str(SHELL_ENTRY), *arguments],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "必须提供一个" in result.stderr


def test_shell_entry_forwards_url_as_one_literal_argument(tmp_path: Path) -> None:
    recorded = tmp_path / "argv.json"
    fake_python = tmp_path / "fake-python"
    fake_python.write_text(
        "#!/bin/sh\n"
        "python3 -c 'import json, os, sys; "
        "open(os.environ[\"RECORDED_ARGV\"], \"w\").write(json.dumps(sys.argv[1:]))' "
        '"$@"\n',
        encoding="utf-8",
    )
    fake_python.chmod(0o755)
    url = "https://x.com/user/status/123?value=$(touch SHOULD_NOT_EXIST)&other=a b"
    env = {
        **os.environ,
        "X2DOC_PUBLISH_PYTHON": str(fake_python),
        "RECORDED_ARGV": str(recorded),
    }

    result = subprocess.run(
        [str(SHELL_ENTRY), url],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    forwarded = json.loads(recorded.read_text(encoding="utf-8"))
    assert len(forwarded) == 2
    assert forwarded[0] == "/Users/paipai_tm/Work/tools/x2doc/scripts/x2doc_publish.py"
    assert forwarded[1] == url
    assert not (tmp_path / "SHOULD_NOT_EXIST").exists()


class StubPublisher:
    def __init__(self, outcome: PublishResult | Exception) -> None:
        self.outcome = outcome
        self.urls: list[str] = []

    def publish(self, url: str) -> PublishResult:
        self.urls.append(url)
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


def test_python_main_prints_success_json(capsys: pytest.CaptureFixture[str]) -> None:
    result = PublishResult(
        markdown="output/x/doc/index.md",
        pdf="output/x/doc/index.pdf",
        output_dir="output/x/doc",
        github_url="https://github.com/PyCodeGuru/x2doc/tree/main/output/x/doc",
        commit="abc123",
        created_commit=True,
    )
    publisher = StubPublisher(result)

    exit_code = publisher_module.main(["https://x.com/user/status/123"], publisher=publisher)

    assert exit_code == 0
    assert publisher.urls == ["https://x.com/user/status/123"]
    assert json.loads(capsys.readouterr().out) == result.as_dict()


def test_python_main_prints_redacted_error_json(capsys: pytest.CaptureFixture[str]) -> None:
    publisher = StubPublisher(
        PublishError(
            "push failed via http://alice:secret@127.0.0.1:7892 "
            "with github_pat_secret123",
            exit_code=3,
        )
    )

    exit_code = publisher_module.main(["https://x.com/user/status/123"], publisher=publisher)

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 3
    assert payload["status"] == "error"
    assert payload["exit_code"] == 3
    assert payload["message"] == (
        "push failed via http://127.0.0.1:7892 with <redacted-token>"
    )


def test_python_main_rejects_wrong_argument_count(capsys: pytest.CaptureFixture[str]) -> None:
    publisher = StubPublisher(RuntimeError("must not run"))

    exit_code = publisher_module.main([], publisher=publisher)

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert publisher.urls == []
    assert payload["status"] == "error"
    assert payload["exit_code"] == 1

