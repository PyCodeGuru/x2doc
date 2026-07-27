from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from x2doc.cli import app
from x2doc.doctor import DoctorCheck, DoctorReport
from x2doc.errors import (
    DependencyError,
    InaccessibleError,
    NetworkError,
    ParameterError,
    RenderError,
)
from x2doc.models import ConversionResult

runner = CliRunner()


def test_cli_success_prints_output_fetch_path_and_warning(tmp_path: Path, monkeypatch) -> None:
    output_dir = tmp_path / "result"
    markdown = output_dir / "index.md"

    def fake_convert(*_args, **_kwargs):
        return ConversionResult(
            output_dir=output_dir,
            outputs={"md": markdown},
            warnings=["请提供 --cookies PATH"],
            fetch_path="syndication",
            cache_path=tmp_path / "cache.json",
        )

    monkeypatch.setattr("x2doc.cli.convert", fake_convert)
    result = runner.invoke(app, ["https://x.com/user/status/1"])

    assert result.exit_code == 0
    assert str(markdown) in result.stdout
    assert "syndication" in result.stdout
    assert "--cookies" in result.stdout


def test_cli_forwards_proxy_to_converter(tmp_path: Path, monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_convert(*_args, **kwargs):
        captured.update(kwargs)
        return ConversionResult(
            output_dir=tmp_path,
            outputs={},
            warnings=[],
            fetch_path="syndication",
            cache_path=tmp_path / "cache.json",
        )

    monkeypatch.setattr("x2doc.cli.convert", fake_convert)
    result = runner.invoke(
        app,
        ["https://x.com/user/status/1", "--proxy", "http://127.0.0.1:7892"],
    )

    assert result.exit_code == 0
    assert captured["proxy"] == "http://127.0.0.1:7892"


def test_doctor_subcommand_prints_report_and_returns_zero(monkeypatch) -> None:
    report = DoctorReport((DoctorCheck("Python", True, "3.12", ""),))
    captured: dict[str, object] = {}

    def fake_doctor(*, cli_proxy=None, **_kwargs):
        captured["proxy"] = cli_proxy
        return report

    monkeypatch.setattr("x2doc.cli.run_doctor", fake_doctor, raising=False)
    result = runner.invoke(app, ["doctor", "--proxy", "http://127.0.0.1:7892"])

    assert result.exit_code == 0
    assert "✅ Python：3.12" in result.stdout
    assert captured["proxy"] == "http://127.0.0.1:7892"


def test_doctor_subcommand_returns_four_when_any_check_fails(monkeypatch) -> None:
    report = DoctorReport(
        (DoctorCheck("Chromium", False, "未安装", "python -m playwright install chromium"),)
    )
    monkeypatch.setattr("x2doc.cli.run_doctor", lambda **_kwargs: report, raising=False)

    result = runner.invoke(app, ["doctor"])

    assert result.exit_code == 4
    assert "❌ Chromium：未安装" in result.stdout


@pytest.mark.parametrize(
    ("error", "exit_code"),
    [
        (ParameterError("bad parameter"), 1),
        (InaccessibleError("protected"), 2),
        (NetworkError("blocked"), 3),
        (DependencyError("missing"), 4),
        (RenderError("broken"), 5),
    ],
)
def test_cli_maps_expected_errors(monkeypatch, error: Exception, exit_code: int) -> None:
    def fail(*_args, **_kwargs):
        raise error

    monkeypatch.setattr("x2doc.cli.convert", fail)
    result = runner.invoke(app, ["https://x.com/user/status/1"])

    assert result.exit_code == exit_code
    assert str(error) in result.stdout


def test_cli_rejects_images_none_with_pdf_before_converter(monkeypatch) -> None:
    called = False

    def fake_convert(*_args, **_kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr("x2doc.cli.convert", fake_convert)
    result = runner.invoke(
        app,
        ["https://x.com/user/status/1", "--format", "pdf", "--images", "none"],
    )

    assert result.exit_code == 1
    assert "互斥" in result.stdout
    assert called is False


@pytest.mark.parametrize("args", [[], ["--unknown-option"]])
def test_click_usage_errors_use_parameter_exit_code_one(args: list[str]) -> None:
    result = runner.invoke(app, args)

    assert result.exit_code == 1
