# -*- coding: utf-8 -*-
"""v1.1.3 start 扫码登录门测试（参数矩阵收敛版）。

--login-wait-seconds 单一参数：
  0（默认）→ start 不阻塞扫码 → 立即 waiting_user_login
  >0       → CLI 内阻塞 N 秒轮询（人工调试兼容）
  <0       → argparse 拒绝

start_service.wait_for_user_login 由 login_wait_seconds > 0 直接推导。
无 --wait-for-login 形参。

覆盖 10 个核心场景：
  1. 默认 start → 不 poll
  2. --login-wait-seconds 0 → 不 poll
  3. --login-wait-seconds 20 → poll，且超时值为 20
  4. 负数拒绝（argparse）
  5. --help 不再出现 --wait-for-login
  6. CDP 已开且已登录 → 原路径不变（waiting_user_confirmation）
  7. CDP 未开 → 只启动一次 Edge
  8. 启动 Edge 后已有持久登录态 → 直接继续
  9. 启动 Edge 后未登录 → waiting_user_login，不创建 run / 不抓 JD
 10. 用户登录后第二次 start → 正常进 waiting_user_confirmation
 11. CDP 启动超时 → 真 browser error
 12. waiting_user_login 只打开一次登录页
 13. CLI stdout 仍然只有合法结构化 JSON
 14. fetch/greet 保留旧 wait_for_user_login=True 阻塞路径

所有浏览器 / patchright / subprocess 都用 mock 隔离。
不连真实 BOSS / 不连真实 CDP。
"""
from __future__ import annotations
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock

import pytest


_HERE = Path(__file__).resolve().parent
_TOOLKIT_ROOT = _HERE.parent
_CLI = _TOOLKIT_ROOT / "boss_hr" / "cli.py"
_SHARED = _TOOLKIT_ROOT / "shared"


# ============================================================
# helpers
# ============================================================

def _ready_ok(**overrides):
    """ensure_browser_ready() 成功：CDP 已连 + BOSS 已登录。"""
    info = {
        "browser_auto_launched": False,
        "login_session_reused": False,
        "login_page_opened": False,
        "page_kind": "recommend",
        "page_url": "https://www.zhipin.com/web/chat/recommend",
        "logged_in": True,
    }
    info.update(overrides)
    @dataclass
    class _R:
        ok: bool = True
        error_obj = None
        remediation = None
        next_action = None
        info: dict = field(default_factory=lambda: info)
    return _R()


def _ready_waiting_login(*, browser_auto_launched=True, login_page_opened=True,
                          login_page_open_error="", **info_overrides):
    """ensure_browser_ready() 在 v1.1.3 默认（wait_for_user_login=False）下未登录。"""
    from boss_hr.contracts.errors import UnifiedError, ErrorCode
    info = {
        "browser_auto_launched": browser_auto_launched,
        "login_page_opened": login_page_opened,
        "login_page_open_error": login_page_open_error,
        "waiting_user_login": True,
        "login_wait_seconds": 0,
    }
    info.update(info_overrides)
    @dataclass
    class _R:
        ok: bool = False
        error_obj = UnifiedError(code=ErrorCode.BOSS_LOGIN_REQUIRED,
                                 message="Edge 已就绪但 BOSS 招聘者尚未登录",
                                 recoverable=True)
        remediation = {"command": "boss-hr start <同样的 query>",
                       "instructions": ["扫码登录", "重跑"]}
        next_action = "login_then_repeat_command"
        info: dict = field(default_factory=lambda: info)
    return _R()


def _ready_real_browser_error(code="EDGE_LAUNCH_FAILED",
                              message="Edge 启动失败"):
    """ensure_browser_ready() 返回真正的浏览器环境错误（非 BOSS_LOGIN_REQUIRED）。"""
    from boss_hr.contracts.errors import UnifiedError, ErrorCode
    @dataclass
    class _R:
        ok: bool = False
        error_obj = UnifiedError(code=ErrorCode(code), message=message,
                                 recoverable=True)
        remediation = {"command": "boss-hr doctor",
                       "instructions": ["诊断"]}
        next_action = "manual_diagnose"
        info: dict = field(default_factory=dict)
    return _R()


# ============================================================
# 1. 默认 start → 不 poll
# ============================================================

def test_default_start_does_not_poll(monkeypatch):
    """login_wait_seconds=0（默认）→ ensure_browser_ready 不轮询，直接返回 waiting_user_login。"""
    from boss_hr.adapters import browser_environment as be
    monkeypatch.setattr(be, "check_python_version", lambda: (True, "3.13.0"))
    monkeypatch.setattr(be, "check_patchright_installed", lambda: True)
    monkeypatch.setattr(be, "check_edge_executable",
                        lambda: r"C:\fake\msedge.exe")
    monkeypatch.setattr(be, "check_cdp_port_listening", lambda *a, **kw: True)
    monkeypatch.setattr(be, "check_cdp_connectable", lambda *a, **kw: (True, ""))
    monkeypatch.setattr(be, "check_boss_logged_in",
                        lambda *a, **kw: (False, {"page_kind": "unknown"}))
    monkeypatch.setattr(be, "_open_login_page", lambda *a, **kw: (True, ""))

    called = {"poll": 0}
    def _fake_poll(*, wait_seconds):
        called["poll"] += 1
        return False, {}
    monkeypatch.setattr(be, "_poll_login_status", _fake_poll)

    r = be.ensure_browser_ready(
        auto_launch=True,
        login_wait_seconds=0,        # 默认
        wait_for_user_login=False,   # start 默认推导
    )
    assert r.ok is False
    assert r.error_obj.code.value == "BOSS_LOGIN_REQUIRED"
    assert called["poll"] == 0, "默认 login_wait_seconds=0 不应轮询登录态"


def test_default_start_via_cli_returns_waiting_user_login(monkeypatch):
    """CLI 默认 start（不传 --login-wait-seconds）→ waiting_user_login。"""
    from boss_hr.application import start_service as ss
    from boss_hr.adapters import legacy_runner
    monkeypatch.setattr(ss, "ensure_browser_ready",
                        lambda *a, **kw: _ready_waiting_login())
    called = {"boss_jd": 0}
    monkeypatch.setattr(legacy_runner, "run_legacy_cli",
                        lambda *a, **kw: called.__setitem__("boss_jd",
                                                           called["boss_jd"] + 1))
    res = ss.start_new_run(query="Q", job_name=None, encrypt_job_id=None,
                            skip_preflight=False, skip_resolve=False,
                            auto_launch_browser=True,
                            login_wait_seconds=0)  # 默认
    d = res.to_dict("start")
    assert d["ok"] is True
    assert d["status"] == "waiting_user_login"
    assert d["next_action"] == "scan_login_then_repeat_start"
    assert called["boss_jd"] == 0


# ============================================================
# 2. --login-wait-seconds 0 → 不 poll
# ============================================================

def test_login_wait_seconds_zero_does_not_poll(monkeypatch):
    """显式 --login-wait-seconds 0 与默认等价：不轮询。"""
    from boss_hr.adapters import browser_environment as be
    monkeypatch.setattr(be, "check_python_version", lambda: (True, "3.13.0"))
    monkeypatch.setattr(be, "check_patchright_installed", lambda: True)
    monkeypatch.setattr(be, "check_edge_executable",
                        lambda: r"C:\fake\msedge.exe")
    monkeypatch.setattr(be, "check_cdp_port_listening", lambda *a, **kw: True)
    monkeypatch.setattr(be, "check_cdp_connectable", lambda *a, **kw: (True, ""))
    monkeypatch.setattr(be, "check_boss_logged_in",
                        lambda *a, **kw: (False, {"page_kind": "unknown"}))
    monkeypatch.setattr(be, "_open_login_page", lambda *a, **kw: (True, ""))

    called = {"poll": 0}
    monkeypatch.setattr(be, "_poll_login_status",
                        lambda *, wait_seconds: called.__setitem__(
                            "poll", called["poll"] + 1) or (False, {}))

    r = be.ensure_browser_ready(
        auto_launch=True,
        login_wait_seconds=0,        # 显式 0
        wait_for_user_login=False,
    )
    assert r.ok is False
    assert called["poll"] == 0


def test_start_with_explicit_zero_returns_waiting_user_login(monkeypatch):
    """start(login_wait_seconds=0) → waiting_user_login。"""
    from boss_hr.application import start_service as ss
    from boss_hr.adapters import legacy_runner
    monkeypatch.setattr(ss, "ensure_browser_ready",
                        lambda *a, **kw: _ready_waiting_login())
    monkeypatch.setattr(legacy_runner, "run_legacy_cli",
                        lambda *a, **kw: MagicMock(returncode=0, stdout="", stderr=""))
    res = ss.start_new_run(query="Q", job_name=None, encrypt_job_id=None,
                            skip_preflight=False, skip_resolve=False,
                            auto_launch_browser=True,
                            login_wait_seconds=0)
    d = res.to_dict("start")
    assert d["ok"] is True
    assert d["status"] == "waiting_user_login"


# ============================================================
# 3. --login-wait-seconds 20 → poll，超时值=20
# ============================================================

def test_login_wait_seconds_twenty_polls_with_that_value(monkeypatch):
    """login_wait_seconds=20 + wait_for_user_login=True（推导）→ 轮询 20s。"""
    from boss_hr.adapters import browser_environment as be
    monkeypatch.setattr(be, "check_python_version", lambda: (True, "3.13.0"))
    monkeypatch.setattr(be, "check_patchright_installed", lambda: True)
    monkeypatch.setattr(be, "check_edge_executable",
                        lambda: r"C:\fake\msedge.exe")
    monkeypatch.setattr(be, "check_cdp_port_listening", lambda *a, **kw: True)
    monkeypatch.setattr(be, "check_cdp_connectable", lambda *a, **kw: (True, ""))
    monkeypatch.setattr(be, "check_boss_logged_in",
                        lambda *a, **kw: (False, {"page_kind": "unknown"}))
    monkeypatch.setattr(be, "_open_login_page", lambda *a, **kw: (True, ""))

    captured = {}
    def _fake_poll(*, wait_seconds):
        captured["wait_seconds"] = wait_seconds
        return False, {}
    monkeypatch.setattr(be, "_poll_login_status", _fake_poll)

    r = be.ensure_browser_ready(
        auto_launch=True,
        login_wait_seconds=20,       # 显式 20
        wait_for_user_login=True,    # start(login_wait_seconds=20) 推导为 True
    )
    assert r.ok is False
    # 关键：轮询超时 = 20
    assert captured.get("wait_seconds") == 20
    # 同时 info.login_wait_seconds=20 透出（兼容路径）
    assert r.info.get("login_wait_seconds") == 20


def test_start_with_login_wait_seconds_twenty_polls(monkeypatch):
    """start(login_wait_seconds=20) → 推导出 wait_for_user_login=True。"""
    from boss_hr.application import start_service as ss
    from boss_hr.adapters import browser_environment as be
    monkeypatch.setattr(ss, "ensure_browser_ready",
                        lambda *a, **kw: _ready_waiting_login(
                            login_wait_seconds=20,
                            login_page_opened=True,
                        ))
    monkeypatch.setattr(ss, "_resolve_recruiter_job",
                        lambda q: {"encryptJobId": "EID",
                                   "jobName": "J",
                                   "jobId": None, "address": "",
                                   "salaryDesc": ""})

    class _OKProc:
        returncode = 0
        stdout = json.dumps({"status": "waiting_user_confirmation",
                             "run_id": "RID_X"}) \
                  + "\nrun_id: RID_X\nSaved to /tmp/x.json\n"
        stderr = ""
    from boss_hr.adapters import legacy_runner
    monkeypatch.setattr(legacy_runner, "run_legacy_cli",
                        lambda *a, **kw: _OKProc())

    res = ss.start_new_run(query="Q", job_name=None, encrypt_job_id=None,
                            skip_preflight=False, skip_resolve=False,
                            auto_launch_browser=True,
                            login_wait_seconds=20)
    # 显式 20 → 走轮询路径（ensure_browser_ready mock 返回 waiting_user_login
    # 用于验证 start 把 BOSS_LOGIN_REQUIRED 翻译为 waiting_user_login）
    d = res.to_dict("start")
    assert d["ok"] is True
    assert d["status"] == "waiting_user_login"


# ============================================================
# 4. 负数拒绝（argparse）
# ============================================================

def test_cli_start_rejects_negative_login_wait_seconds():
    """`boss-hr start ... --login-wait-seconds -5` 必须被 argparse 拒绝（rc=2）。"""
    res = subprocess.run(
        [sys.executable, "-X", "utf8", str(_CLI),
         "start", "某岗位", "--login-wait-seconds", "-5"],
        capture_output=True, env={**os.environ, "PYTHONUTF8": "1",
                                  "PYTHONIOENCODING": "utf-8",
                                  "PYTHONPATH": str(_SHARED)},
        cwd=str(_TOOLKIT_ROOT), timeout=15,
    )
    # argparse error → exit code 2
    assert res.returncode == 2
    err = res.stderr.decode("utf-8", errors="replace")
    assert "--login-wait-seconds" in err
    assert ">= 0" in err or "大于等于 0" in err


def test_cli_start_rejects_non_integer_login_wait_seconds():
    """`boss-hr start ... --login-wait-seconds abc` → argparse 拒绝。"""
    res = subprocess.run(
        [sys.executable, "-X", "utf8", str(_CLI),
         "start", "某岗位", "--login-wait-seconds", "abc"],
        capture_output=True, env={**os.environ, "PYTHONUTF8": "1",
                                  "PYTHONIOENCODING": "utf-8",
                                  "PYTHONPATH": str(_SHARED)},
        cwd=str(_TOOLKIT_ROOT), timeout=15,
    )
    assert res.returncode == 2
    err = res.stderr.decode("utf-8", errors="replace")
    assert "--login-wait-seconds" in err


# ============================================================
# 5. --help 不再出现 --wait-for-login
# ============================================================

def test_cli_start_help_does_not_contain_wait_for_login():
    """`boss-hr start --help` 不应再出现 --wait-for-login。"""
    res = subprocess.run(
        [sys.executable, "-X", "utf8", str(_CLI), "start", "--help"],
        capture_output=True, env={**os.environ, "PYTHONUTF8": "1",
                                  "PYTHONIOENCODING": "utf-8",
                                  "PYTHONPATH": str(_SHARED)},
        cwd=str(_TOOLKIT_ROOT), timeout=15,
    )
    text = res.stdout.decode("utf-8", errors="replace")
    assert "--login-wait-seconds" in text
    assert "--wait-for-login" not in text


# ============================================================
# 6. CDP 已开且已登录 → waiting_user_confirmation
# ============================================================

def test_start_cdp_open_and_logged_in_unchanged(monkeypatch):
    """CDP 已开 + 已登录 → start 直接进 waiting_user_confirmation（不引入新状态）。"""
    from boss_hr.application import start_service as ss
    from boss_hr.adapters import legacy_runner
    monkeypatch.setattr(ss, "ensure_browser_ready",
                        lambda *a, **kw: _ready_ok())
    monkeypatch.setattr(ss, "_resolve_recruiter_job",
                        lambda q: {"encryptJobId": "EID1",
                                   "jobName": "某岗位",
                                   "jobId": None, "address": "", "salaryDesc": ""})

    class _OKProc:
        returncode = 0
        stdout = json.dumps({"status": "waiting_user_confirmation",
                             "run_id": "2026-08-07_100000"}) \
                  + "\nrun_id: 2026-08-07_100000\nSaved to /tmp/x.json\n"
        stderr = ""
    monkeypatch.setattr(legacy_runner, "run_legacy_cli",
                        lambda *a, **kw: _OKProc())

    res = ss.start_new_run(query="某岗位", job_name=None, encrypt_job_id=None,
                            skip_preflight=False, skip_resolve=False,
                            auto_launch_browser=True,
                            login_wait_seconds=0)
    d = res.to_dict("start")
    assert d["ok"] is True
    assert d["status"] == "waiting_user_confirmation"
    assert d["run_id"] == "2026-08-07_100000"
    assert d["next_action"] == "confirm"


# ============================================================
# 7. CDP 未开 → 只启动一次 Edge
# ============================================================

def test_ensure_browser_ready_no_cdp_launches_edge_once(monkeypatch):
    """CDP 未监听 → launch_dedicated_edge 只能被调用 1 次，不重复启动。"""
    from boss_hr.adapters import browser_environment as be
    monkeypatch.setattr(be, "check_python_version", lambda: (True, "3.13.0"))
    monkeypatch.setattr(be, "check_patchright_installed", lambda: True)
    monkeypatch.setattr(be, "check_edge_executable",
                        lambda: r"C:\fake\msedge.exe")
    monkeypatch.setattr(be, "check_cdp_port_listening", lambda *a, **kw: False)
    monkeypatch.setattr(be, "check_cdp_connectable", lambda *a, **kw: (True, ""))
    monkeypatch.setattr(be, "check_boss_logged_in",
                        lambda *a, **kw: (True, {"page_kind": "recommend"}))

    captured = {"count": 0}
    def _fake_launch(*a, **kw):
        captured["count"] += 1
        from boss_hr.adapters.browser_environment import _EdgeLaunch
        return _EdgeLaunch(ok=True, edge_path="x", profile_dir="y")
    monkeypatch.setattr(be, "launch_dedicated_edge", _fake_launch)

    r = be.ensure_browser_ready(
        auto_launch=True,
        login_wait_seconds=0,
        wait_for_user_login=False,
    )
    assert r.ok is True
    assert captured["count"] == 1


# ============================================================
# 8. 启动 Edge 后已有持久登录态 → 直接继续
# ============================================================

def test_start_edge_just_started_with_persistent_login_proceeds(monkeypatch):
    """Edge 刚自动启动 + cookies 立即有效 → start 不该返回 waiting_user_login。"""
    from boss_hr.application import start_service as ss
    from boss_hr.adapters import legacy_runner
    monkeypatch.setattr(ss, "ensure_browser_ready",
                        lambda *a, **kw: _ready_ok(browser_auto_launched=True,
                                                   login_session_reused=True))
    monkeypatch.setattr(ss, "_resolve_recruiter_job",
                        lambda q: {"encryptJobId": "EID2",
                                   "jobName": "某岗位",
                                   "jobId": None, "address": "", "salaryDesc": ""})

    class _OKProc:
        returncode = 0
        stdout = json.dumps({"status": "waiting_user_confirmation",
                             "run_id": "2026-08-07_100001"}) \
                  + "\nrun_id: 2026-08-07_100001\nSaved to /tmp/x.json\n"
        stderr = ""
    monkeypatch.setattr(legacy_runner, "run_legacy_cli",
                        lambda *a, **kw: _OKProc())

    res = ss.start_new_run(query="某岗位", job_name=None, encrypt_job_id=None,
                            skip_preflight=False, skip_resolve=False,
                            auto_launch_browser=True,
                            login_wait_seconds=0)
    d = res.to_dict("start")
    assert d["ok"] is True
    assert d["status"] == "waiting_user_confirmation"
    assert "waiting_user_login" not in d.get("status", "")


# ============================================================
# 9. 启动 Edge 后未登录 → waiting_user_login，不创建 run
# ============================================================

def test_start_no_login_after_launch_returns_waiting_user_login(monkeypatch):
    """v1.1.3：start 默认 login_wait_seconds=0 → 立即返回 waiting_user_login。"""
    from boss_hr.application import start_service as ss
    from boss_hr.adapters import legacy_runner
    called = {"boss_jd": 0, "resolve": 0}
    monkeypatch.setattr(ss, "ensure_browser_ready",
                        lambda *a, **kw: _ready_waiting_login(
                            browser_auto_launched=True,
                            login_page_opened=True))
    monkeypatch.setattr(legacy_runner, "run_legacy_cli",
                        lambda *a, **kw: called.__setitem__(
                            "boss_jd", called["boss_jd"] + 1) or MagicMock(
                            returncode=0, stdout="", stderr=""))
    monkeypatch.setattr(ss, "_resolve_recruiter_job",
                        lambda q: called.__setitem__(
                            "resolve", called["resolve"] + 1) or {
                            "encryptJobId": "E", "jobName": "J",
                            "jobId": None, "address": "", "salaryDesc": ""})

    res = ss.start_new_run(query="Q", job_name=None, encrypt_job_id=None,
                            skip_preflight=False, skip_resolve=False,
                            auto_launch_browser=True,
                            login_wait_seconds=0)
    d = res.to_dict("start")
    assert d["ok"] is True
    assert d["status"] == "waiting_user_login"
    assert d["next_action"] == "scan_login_then_repeat_start"
    assert d["data"]["login_page_opened"] is True
    assert d["data"]["waiting_user_login"] is True
    assert "重新执行同一条 start" in d["message"]
    # 关键不变量
    assert called["boss_jd"] == 0
    assert called["resolve"] == 0


def test_waiting_user_login_does_not_create_run_or_jd(monkeypatch):
    """waiting_user_login 路径下：boss_jd 不被调；run_id 为空。"""
    from boss_hr.application import start_service as ss
    from boss_hr.adapters import legacy_runner

    monkeypatch.setattr(ss, "ensure_browser_ready",
                        lambda *a, **kw: _ready_waiting_login())
    monkeypatch.setattr(ss, "_resolve_recruiter_job",
                        lambda q: {"encryptJobId": "EID",
                                   "jobName": "J",
                                   "jobId": None, "address": "",
                                   "salaryDesc": ""})

    def _guard(*a, **kw):
        raise AssertionError("waiting_user_login 不应调 boss_jd")
    monkeypatch.setattr(legacy_runner, "run_legacy_cli", _guard)

    res = ss.start_new_run(query="Q", job_name=None, encrypt_job_id=None,
                            skip_preflight=False, skip_resolve=False,
                            auto_launch_browser=True,
                            login_wait_seconds=0)
    d = res.to_dict("start")
    assert d["ok"] is True
    assert d["status"] == "waiting_user_login"
    assert d.get("run_id") in (None, ""), (
        f"waiting_user_login 不应带 run_id，实际={d.get('run_id')!r}")


# ============================================================
# 10. 用户登录后第二次 start → waiting_user_confirmation
# ============================================================

def test_second_start_after_user_login_proceeds(monkeypatch):
    """第二次 start（用户已扫码）→ ensure_browser_ready 返回 ok=True → waiting_user_confirmation。"""
    from boss_hr.application import start_service as ss
    from boss_hr.adapters import legacy_runner
    monkeypatch.setattr(ss, "ensure_browser_ready",
                        lambda *a, **kw: _ready_ok(
                            browser_auto_launched=False))
    monkeypatch.setattr(ss, "_resolve_recruiter_job",
                        lambda q: {"encryptJobId": "EID3",
                                   "jobName": "某岗位",
                                   "jobId": None, "address": "",
                                   "salaryDesc": ""})

    class _OKProc:
        returncode = 0
        stdout = json.dumps({"status": "waiting_user_confirmation",
                             "run_id": "2026-08-07_100002"}) \
                  + "\nrun_id: 2026-08-07_100002\nSaved to /tmp/x.json\n"
        stderr = ""
    monkeypatch.setattr(legacy_runner, "run_legacy_cli",
                        lambda *a, **kw: _OKProc())

    res = ss.start_new_run(query="某岗位", job_name=None, encrypt_job_id=None,
                            skip_preflight=False, skip_resolve=False,
                            auto_launch_browser=True,
                            login_wait_seconds=0)
    d = res.to_dict("start")
    assert d["ok"] is True
    assert d["status"] == "waiting_user_confirmation"
    assert d["run_id"] == "2026-08-07_100002"
    assert d["next_action"] == "confirm"


# ============================================================
# 11. CDP 启动超时 → 真 browser error
# ============================================================

def test_start_cdp_launch_failure_returns_real_error(monkeypatch):
    """CDP 启动失败 → start 返回 CDP_NOT_RUNNING/EDGE_LAUNCH_FAILED（非 waiting_user_login）。"""
    from boss_hr.application import start_service as ss
    from boss_hr.adapters import legacy_runner

    monkeypatch.setattr(ss, "ensure_browser_ready",
                        lambda *a, **kw: _ready_real_browser_error(
                            code="CDP_NOT_RUNNING",
                            message="Edge 已启动但 9222 未监听"))
    monkeypatch.setattr(ss, "_resolve_recruiter_job",
                        lambda q: {"encryptJobId": "EID",
                                   "jobName": "J",
                                   "jobId": None, "address": "",
                                   "salaryDesc": ""})

    def _guard(*a, **kw):
        raise AssertionError("CDP 启动失败不应调 boss_jd")
    monkeypatch.setattr(legacy_runner, "run_legacy_cli", _guard)

    res = ss.start_new_run(query="Q", job_name=None, encrypt_job_id=None,
                            skip_preflight=False, skip_resolve=True,
                            auto_launch_browser=True,
                            login_wait_seconds=0)
    d = res.to_dict("start")
    assert d["ok"] is False
    assert d["error"]["code"] in ("CDP_NOT_RUNNING", "EDGE_LAUNCH_FAILED",
                                   "EDGE_NOT_FOUND", "CDP_CONNECT_FAILED")
    assert d.get("status") != "waiting_user_login"
    assert d.get("next_action") != "scan_login_then_repeat_start"


# ============================================================
# 12. waiting_user_login 只打开一次登录页
# ============================================================

def test_waiting_user_login_opens_login_page_only_once(monkeypatch):
    """未登录时只调一次 _open_login_page，不重复。"""
    from boss_hr.adapters import browser_environment as be
    monkeypatch.setattr(be, "check_python_version", lambda: (True, "3.13.0"))
    monkeypatch.setattr(be, "check_patchright_installed", lambda: True)
    monkeypatch.setattr(be, "check_edge_executable",
                        lambda: r"C:\fake\msedge.exe")
    monkeypatch.setattr(be, "check_cdp_port_listening", lambda *a, **kw: True)
    monkeypatch.setattr(be, "check_cdp_connectable", lambda *a, **kw: (True, ""))
    monkeypatch.setattr(be, "check_boss_logged_in",
                        lambda *a, **kw: (False, {"page_kind": "unknown"}))

    called = {"open": 0}
    monkeypatch.setattr(be, "_open_login_page",
                        lambda *a, **kw: called.__setitem__(
                            "open", called["open"] + 1) or (True, ""))

    r = be.ensure_browser_ready(
        auto_launch=True,
        login_wait_seconds=0,
        wait_for_user_login=False,
    )
    assert r.ok is False
    assert called["open"] == 1


# ============================================================
# 13. CLI stdout 仍然只有合法结构化 JSON
# ============================================================

def test_cli_start_waiting_user_login_emit_structured_json(tmp_path):
    """CLI `boss-hr start Q` → waiting_user_login → stdout 只有合法 JSON，rc=0。"""
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8",
           "PYTHONPATH": str(_SHARED), "BOSS_HR_OUTPUT_DIR": str(tmp_path),
           "BOSS_HR_TEST_PREFLIGHT_WAITING": "1"}
    res = subprocess.run(
        [sys.executable, "-X", "utf8", str(_CLI), "start", "某岗位",
         "--no-auto-launch"],
        capture_output=True, env=env,
        cwd=str(_TOOLKIT_ROOT), timeout=20,
    )
    out = res.stdout.decode("utf-8", errors="replace").strip()
    assert out, "stdout 不应为空"
    parsed = json.loads(out.splitlines()[-1])
    assert parsed["ok"] is True
    assert parsed["command"] == "start"
    assert parsed["status"] == "waiting_user_login"
    assert parsed["next_action"] == "scan_login_then_repeat_start"
    assert res.returncode == 0
    err = res.stderr.decode("utf-8", errors="replace")
    assert "Traceback" not in err


# ============================================================
# 14. fetch / greet 保留旧 wait_for_user_login=True 阻塞路径
# ============================================================

def test_fetch_still_uses_blocking_poll():
    """fetch_service 源码检查：传 wait_for_user_login=True 保留旧轮询路径。"""
    import inspect
    import boss_hr.application.fetch_service as fs
    src = inspect.getsource(fs.fetch_candidates)
    assert "wait_for_user_login=True" in src, (
        "fetch_service.fetch_candidates 应保留旧 wait_for_user_login=True "
        "阻塞路径（v1.1.3 只修 start；fetch/greet 行为不变）")
    assert "ensure_browser_ready(" in src


def test_greet_still_uses_blocking_poll():
    """greet_service 源码检查：传 wait_for_user_login=True 保留旧轮询路径。"""
    import inspect
    import boss_hr.application.greet_service as gs
    src = inspect.getsource(gs.greet_candidates)
    assert "wait_for_user_login=True" in src, (
        "greet_service.greet_candidates 应保留旧 wait_for_user_login=True "
        "阻塞路径（v1.1.3 只修 start；fetch/greet 行为不变）")
    assert "ensure_browser_ready(" in src


# ============================================================
# 15. start_service 不再接受 wait_for_user_login 形参
# ============================================================

def test_start_service_signature_has_no_wait_for_user_login_kwarg():
    """v1.1.3：start_new_run 不再有 wait_for_user_login 关键字形参。"""
    import inspect
    import boss_hr.application.start_service as ss
    sig = inspect.signature(ss.start_new_run)
    assert "wait_for_user_login" not in sig.parameters, (
        "start_new_run 不应再有 wait_for_user_login 形参（由 login_wait_seconds > 0 推导）")
    assert "login_wait_seconds" in sig.parameters


def test_start_service_derives_wait_for_user_login_from_login_wait_seconds(monkeypatch):
    """start_service 内部由 login_wait_seconds > 0 推导 wait_for_user_login，传给 ensure_browser_ready。"""
    from boss_hr.application import start_service as ss
    from boss_hr.adapters import legacy_runner

    captured = {}
    def _fake_ensure(*, auto_launch=False, login_wait_seconds=0,
                     wait_for_user_login=False):
        captured["auto_launch"] = auto_launch
        captured["login_wait_seconds"] = login_wait_seconds
        captured["wait_for_user_login"] = wait_for_user_login
        return _ready_waiting_login(login_wait_seconds=login_wait_seconds)

    monkeypatch.setattr(ss, "ensure_browser_ready", _fake_ensure)
    monkeypatch.setattr(legacy_runner, "run_legacy_cli",
                        lambda *a, **kw: MagicMock(returncode=0, stdout="",
                                                   stderr=""))

    # login_wait_seconds=0 → wait_for_user_login=False
    ss.start_new_run(query="Q", job_name=None, encrypt_job_id=None,
                     skip_preflight=False, skip_resolve=True,
                     auto_launch_browser=True,
                     login_wait_seconds=0)
    assert captured.get("wait_for_user_login") is False

    # login_wait_seconds=15 → wait_for_user_login=True
    ss.start_new_run(query="Q", job_name=None, encrypt_job_id=None,
                     skip_preflight=False, skip_resolve=True,
                     auto_launch_browser=True,
                     login_wait_seconds=15)
    assert captured.get("wait_for_user_login") is True
    assert captured.get("login_wait_seconds") == 15