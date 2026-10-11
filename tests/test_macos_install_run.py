"""macOS 浏览器路径和本地 CLI 的离线回归测试。"""
from pathlib import Path

from boss_hr.adapters import browser_environment as be
from boss_hr.adapters import browser_preflight as bp
from boss_hr.application import doctor_service as ds


def test_macos_finds_installed_chrome(monkeypatch):
    monkeypatch.setattr(bp.sys, "platform", "darwin")
    monkeypatch.setattr(bp.os.path, "isfile",
                        lambda p: p == "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
    assert bp.check_edge_executable() == "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    assert bp.browser_name() == "Google Chrome"


def test_macos_uses_separate_profile_and_local_cdp(monkeypatch):
    monkeypatch.setattr(be.sys, "platform", "darwin")
    profile = be._dedicated_profile_dir()
    assert profile.endswith("/Library/Application Support/HR-recruiting-assistant/chrome-profile")
    assert "/Google/Chrome/" not in profile
    cmd = be._build_edge_launch_command("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", profile)
    assert f"--user-data-dir={profile}" in cmd
    assert "--remote-debugging-port=9222" in cmd
    assert "--remote-debugging-address=127.0.0.1" in cmd
    assert "--remote-allow-origins=*" not in cmd
    assert ds._default_profile_dir() == profile


def test_existing_cdp_does_not_require_browser_lookup(monkeypatch):
    monkeypatch.setattr(be, "check_python_version", lambda: (True, "3.14.0"))
    monkeypatch.setattr(be, "check_patchright_installed", lambda: True)
    monkeypatch.setattr(be, "check_cdp_port_listening", lambda: True)
    monkeypatch.setattr(be, "check_edge_executable", lambda: None)
    monkeypatch.setattr(be, "check_cdp_connectable", lambda url: (True, ""))
    monkeypatch.setattr(be, "check_boss_logged_in", lambda url: (
        True, {"page_kind": "recommend", "current_url": "https://www.zhipin.com/web/chat/recommend"}
    ))
    result = be.ensure_browser_ready(auto_launch=True)
    assert result.ok is True
    assert result.info["browser_auto_launched"] is False


def test_doctor_accepts_cross_platform_launch_option():
    from boss_hr.cli import build_parser
    parser = build_parser()
    assert parser.parse_args(["doctor", "--launch-browser"]).launch_edge is True
    assert parser.parse_args(["doctor", "--launch-edge"]).launch_edge is True


def test_macos_install_script_is_present():
    assert (Path(__file__).resolve().parents[1] / "install-macos.sh").is_file()
