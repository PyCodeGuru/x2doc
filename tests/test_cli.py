from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from x2doc.cli import app
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
