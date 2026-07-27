from __future__ import annotations

from x2doc.doctor import (
    DoctorCheck,
    check_proxy,
    format_bytes,
    proxy_source,
    render_report,
    run_doctor,
)


def test_doctor_runs_every_check_after_failure() -> None:
    calls: list[str] = []

    def check(name: str, ok: bool):
        def execute() -> DoctorCheck:
            calls.append(name)
            return DoctorCheck(name, ok, "detail", "修复命令")

        return execute

    report = run_doctor([check("one", False), check("two", True), check("three", False)])

    assert calls == ["one", "two", "three"]
    assert report.ok is False
    assert report.exit_code == 4


def test_doctor_runs_all_nine_injected_checks() -> None:
    calls: list[int] = []

    def make_check(index: int):
        def execute() -> DoctorCheck:
            calls.append(index)
            return DoctorCheck(str(index), index != 4, "detail", "fix")

        return execute

    report = run_doctor([make_check(index) for index in range(1, 10)])

    assert calls == list(range(1, 10))
    assert len(report.checks) == 9
    assert report.exit_code == 4


def test_successful_report_uses_checkmarks_and_exit_zero() -> None:
    report = run_doctor([lambda: DoctorCheck("Python", True, "3.12", "")])

    output = render_report(report)

    assert report.exit_code == 0
    assert "✅ Python：3.12" in output
    assert "全部通过" in output


def test_failed_report_prints_cross_and_copyable_fix() -> None:
    report = run_doctor(
        [lambda: DoctorCheck("Chromium", False, "未安装", "python -m playwright install chromium")]
    )

    output = render_report(report)

    assert "❌ Chromium：未安装" in output
    assert "修复：python -m playwright install chromium" in output
    assert "1 项失败" in output


def test_proxy_source_obeys_precedence_and_redacts_credentials() -> None:
    environment = {
        "X2DOC_PROXY": "http://env-user:env-pass@env.test:8080",
        "HTTPS_PROXY": "http://https.test:8081",
        "ALL_PROXY": "socks5://all.test:1080",
    }

    source, proxy = proxy_source("http://cli-user:cli-pass@127.0.0.1:7892", environ=environment)

    assert source == "--proxy"
    assert proxy is not None
    assert proxy.redacted == "http://127.0.0.1:7892"
    assert "cli-user" not in proxy.redacted
    assert "cli-pass" not in proxy.redacted


def test_direct_connection_is_a_valid_proxy_mode() -> None:
    check = check_proxy("直连", None)

    assert check.ok is True
    assert check.detail.startswith("直连（未配置显式代理）")
    assert "mp.weixin.qq.com" in check.detail


def test_default_doctor_includes_wechat_source_and_image(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("x2doc.doctor.check_python", lambda: DoctorCheck("1", True, "ok", ""))
    monkeypatch.setattr("x2doc.doctor.check_package", lambda: DoctorCheck("2", True, "ok", ""))
    monkeypatch.setattr("x2doc.doctor.check_chromium", lambda: DoctorCheck("3", True, "ok", ""))
    monkeypatch.setattr("x2doc.doctor.check_font", lambda: DoctorCheck("4", True, "ok", ""))
    monkeypatch.setattr(
        "x2doc.doctor.check_data_sources", lambda _proxy: DoctorCheck("6", True, "ok", "")
    )
    monkeypatch.setattr(
        "x2doc.doctor.check_image_source", lambda _proxy: DoctorCheck("7", True, "ok", "")
    )
    monkeypatch.setattr(
        "x2doc.doctor.check_wechat_source", lambda: DoctorCheck("10", True, "直连", "")
    )
    monkeypatch.setattr(
        "x2doc.doctor.check_wechat_image", lambda: DoctorCheck("11", True, "Referer", "")
    )

    report = run_doctor(environ={}, cwd=tmp_path)

    assert len(report.checks) == 11
    assert report.checks[-2].name == "10"
    assert report.checks[-1].name == "11"


def test_format_bytes_is_deterministic() -> None:
    assert format_bytes(0) == "0 B"
    assert format_bytes(1536) == "1.5 KiB"
    assert format_bytes(2 * 1024 * 1024) == "2.0 MiB"
