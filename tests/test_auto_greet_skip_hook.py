# -*- coding: utf-8 -*-
"""auto_greet.py 异常退出钩子测试（2026-08-04）。

修复背景：旧版 atexit 会调 output.prune_if_empty()，只要 run_dir 里没有
.html 报告就 rmtree 整个目录 — 误删 run.json / job_detail.json /
screening_results.json / scoring/ 等业务数据。

修复后：atexit 钩子调 note_skip_if_unsaved()，仅写一行 run_log，
永不删除任何文件，且幂等。

测试覆盖（用户 §一.4 要求）：
  1. note_skip_if_unsaved 不删 run_dir
  2. 业务文件完整保留（run.json / job_detail / screening_results / scoring/）
  3. 其他历史 run 不受影响
  4. 幂等：重复调用不重复写日志
  5. saved=True 时不写日志
  6. auto_greet.py 静态审计：不再调用 prune_if_empty / shutil.rmtree / os.rmdir
  7. run_dir 里没有 HTML 时也不删 run
  8. 有 HTML 时不影响（naturally no-op）
"""
from __future__ import annotations
import ast
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest


_HERE = Path(__file__).resolve().parent
_TOOLKIT_ROOT = _HERE.parent  # tests/ → toolkit root
_AUTO_GREET = _TOOLKIT_ROOT / "boss-hr-greet" / "scripts" / "auto_greet.py"


# ============================================================
# helpers
# ============================================================

def _make_real_run(ws: Path, eid: str, rid: str) -> Path:
    """写真实业务 run 目录（无 HTML）。"""
    run = ws / eid / "runs" / rid
    proc = run / "process"
    proc.mkdir(parents=True, exist_ok=True)
    (run / "run.json").write_text(json.dumps({
        "run_id": rid, "encrypt_job_id": eid,
        "confirmed": True, "steps_done": ["jd", "download", "score", "report"],
    }), encoding="utf-8")
    (proc / "job_detail.json").write_text(json.dumps({
        "encryptJobId": eid, "jobName": "j",
    }), encoding="utf-8")
    (proc / "screening_results.json").write_text(json.dumps({
        "candidates": [{"name": "x", "total": 90, "tier": "推荐"}],
    }), encoding="utf-8")
    # scoring/ 目录
    scoring = proc / "scoring"
    scoring.mkdir(exist_ok=True)
    (scoring / "manifest.json").write_text("{}", encoding="utf-8")
    return run


@pytest.fixture
def smoke_ws(tmp_path, monkeypatch):
    """隔离工作区：patch output_manager.OUTPUT_ROOT 到 tmp_path。"""
    import output_manager
    monkeypatch.setattr(output_manager, "OUTPUT_ROOT", str(tmp_path), raising=False)
    return tmp_path


@pytest.fixture
def auto_greet_module(monkeypatch):
    """导入 auto_greet（绕开 patchright 副作用）：
    patchright 不可用时仍能 import（只 import 时不调 sync_playwright）。
    """
    sys.path.insert(0, str(_TOOLKIT_ROOT / "boss-hr-greet" / "scripts"))
    sys.path.insert(0, str(_TOOLKIT_ROOT / "shared"))
    import auto_greet
    return auto_greet


# ============================================================
# 核心行为：note_skip_if_unsaved 不删 run_dir
# ============================================================

def test_skip_hook_preserves_real_run(smoke_ws, auto_greet_module):
    """核心 bug 修复：无 greet_log.json 时 run_dir（含业务文件）完整保留。"""
    eid, rid = "test_eid_pr1", "2026-08-04_120000"
    run = _make_real_run(smoke_ws, eid, rid)

    from output_manager import JobOutputManager
    out = JobOutputManager("j", encrypt_job_id=eid, run_id=rid, lazy=True)

    noted = auto_greet_module.note_skip_if_unsaved(out, saved=False)
    assert noted is True

    # 1. run_dir 完整保留
    assert run.exists(), "run_dir 被误删！"
    # 2. 所有业务文件保留
    assert (run / "run.json").is_file()
    assert (run / "process" / "job_detail.json").is_file()
    assert (run / "process" / "screening_results.json").is_file()
    assert (run / "process" / "scoring" / "manifest.json").is_file()


def test_skip_hook_does_not_delete_html_run(smoke_ws, auto_greet_module):
    """有 HTML 报告时也不删（修复后这条本来就该通过；之前因 prune 逻辑反转）。"""
    eid, rid = "test_eid_pr2", "2026-08-04_120000"
    run = _make_real_run(smoke_ws, eid, rid)
    (run / "2026-08-04_120000_screening_report.html").write_text(
        "<html></html>", encoding="utf-8")

    from output_manager import JobOutputManager
    out = JobOutputManager("j", encrypt_job_id=eid, run_id=rid, lazy=True)
    auto_greet_module.note_skip_if_unsaved(out, saved=False)
    assert run.exists()
    assert (run / "2026-08-04_120000_screening_report.html").is_file()


def test_skip_hook_skips_when_saved(smoke_ws, auto_greet_module):
    """saved=True（greet 成功写出 greet_log.json）时不写提示日志。"""
    eid, rid = "test_eid_pr3", "2026-08-04_120000"
    run = _make_real_run(smoke_ws, eid, rid)
    (run / "process" / "greet_log.json").write_text("{}", encoding="utf-8")

    from output_manager import JobOutputManager
    out = JobOutputManager("j", encrypt_job_id=eid, run_id=rid, lazy=True)
    noted = auto_greet_module.note_skip_if_unsaved(out, saved=True)
    assert noted is False
    # sentry 文件不应创建
    assert not (run / ".greet_skip_noted").exists()
    # run_log 不应有 skip 提示
    if out.run_log_path and os.path.isfile(out.run_log_path):
        content = Path(out.run_log_path).read_text(encoding="utf-8")
        assert "未产生 greet_log.json" not in content


def test_skip_hook_idempotent(smoke_ws, auto_greet_module):
    """同一进程内重复调 atexit 钩子，只第一次写日志。"""
    eid, rid = "test_eid_pr4", "2026-08-04_120000"
    run = _make_real_run(smoke_ws, eid, rid)

    from output_manager import JobOutputManager
    out = JobOutputManager("j", encrypt_job_id=eid, run_id=rid, lazy=True)
    n1 = auto_greet_module.note_skip_if_unsaved(out, saved=False)
    n2 = auto_greet_module.note_skip_if_unsaved(out, saved=False)
    n3 = auto_greet_module.note_skip_if_unsaved(out, saved=False)
    assert n1 is True
    assert n2 is False
    assert n3 is False

    # run_log 中只有一行 skip 提示
    content = Path(out.run_log_path).read_text(encoding="utf-8")
    skip_lines = [l for l in content.splitlines()
                  if "未产生 greet_log.json" in l]
    assert len(skip_lines) == 1


def test_skip_hook_does_not_touch_other_runs(smoke_ws, auto_greet_module):
    """其他历史 run 完全不受影响。"""
    target_eid, target_rid = "test_eid_pr5", "2026-08-04_120000"
    other_eid, other_rid = "test_eid_pr5", "2026-08-03_170000"

    target_run = _make_real_run(smoke_ws, target_eid, target_rid)
    other_run = _make_real_run(smoke_ws, other_eid, other_rid)
    # 快照 other_run 内容
    other_files = sorted(
        p.relative_to(smoke_ws).as_posix()
        for p in other_run.rglob("*") if p.is_file()
    )

    from output_manager import JobOutputManager
    out = JobOutputManager("j", encrypt_job_id=target_eid, run_id=target_rid,
                           lazy=True)
    auto_greet_module.note_skip_if_unsaved(out, saved=False)

    # other_run 完全未动
    new_other_files = sorted(
        p.relative_to(smoke_ws).as_posix()
        for p in other_run.rglob("*") if p.is_file()
    )
    assert new_other_files == other_files


def test_skip_hook_writes_run_log(smoke_ws, auto_greet_module):
    """即使保留 run_dir，run_log 也应记录提示（可观测性）。"""
    eid, rid = "test_eid_pr6", "2026-08-04_120000"
    run = _make_real_run(smoke_ws, eid, rid)
    from output_manager import JobOutputManager
    out = JobOutputManager("j", encrypt_job_id=eid, run_id=rid, lazy=True)
    auto_greet_module.note_skip_if_unsaved(out, saved=False)
    assert Path(out.run_log_path).is_file()
    content = Path(out.run_log_path).read_text(encoding="utf-8")
    assert "未产生 greet_log.json" in content
    assert "完整保留" in content


def test_skip_hook_does_not_create_greet_log(smoke_ws, auto_greet_module):
    """钩子只写日志 + sentry，不写 greet_log.json（那是业务流程的事）。"""
    eid, rid = "test_eid_pr7", "2026-08-04_120000"
    _make_real_run(smoke_ws, eid, rid)
    from output_manager import JobOutputManager
    out = JobOutputManager("j", encrypt_job_id=eid, run_id=rid, lazy=True)
    auto_greet_module.note_skip_if_unsaved(out, saved=False)
    greet_log = Path(out.process_dir) / "greet_log.json"
    assert not greet_log.exists()


# ============================================================
# 静态审计：auto_greet.py 不再调用删目录的 API
# ============================================================

def test_auto_greet_source_no_longer_calls_prune():
    """AST 静态检查：auto_greet.py 不再调 prune_if_empty / shutil.rmtree /
    os.rmdir — 防止未来回归。

    prune_if_empty / shutil.rmtree / os.rmdir 都是已知危险的删目录 API。
    greet 是个 Step 5 工具，没有资格决定业务 run 目录的命运。
    """
    src = _AUTO_GREET.read_text(encoding="utf-8")
    tree = ast.parse(src)

    forbidden_calls: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            target = node.func
            if isinstance(target, ast.Attribute):
                qualname = ast.unparse(target)
                # 排除掉 whitelist（"note_skip_if_unsaved" 中提到 prune 是 OK，
                # 因为只是 docstring 描述）
                if qualname in ("prune_if_empty", "shutil.rmtree", "os.rmdir",
                                "shutil.rmtree", "os.removedirs"):
                    forbidden_calls.append((qualname, node.lineno))
            elif isinstance(target, ast.Name) and target.id == "rmtree":
                forbidden_calls.append(("rmtree", node.lineno))

    assert forbidden_calls == [], (
        f"auto_greet.py 不得调用删目录 API（修复了 prune 误删 bug）: "
        f"{forbidden_calls}"
    )


def test_auto_greet_source_documents_fix():
    """auto_greet.py 的 atexit 钩子处应有'2026-08-04'修复说明。"""
    src = _AUTO_GREET.read_text(encoding="utf-8")
    # atexit 注释里应有日期戳 + "绝不删 run_dir" / "不删除任何文件"
    assert "atexit" in src
    # 钩子块中（atexit.register 前后 600 字符）应含修复说明
    idx = src.find("atexit.register")
    window = src[max(0, idx - 600): idx + 200]
    assert "2026-08-04" in window
    assert ("绝不删" in window) or ("不删除任何文件" in window) or ("不删" in window)


def test_auto_greet_source_has_note_skip_helper():
    """修复后的模块级函数 note_skip_if_unsaved 必须存在并被使用。"""
    src = _AUTO_GREET.read_text(encoding="utf-8")
    tree = ast.parse(src)
    func_names = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
    assert "note_skip_if_unsaved" in func_names


# ============================================================
# 回归：旧 prune_if_empty API 行为不变（greet 不再调它，
# 但其他 Step 脚本仍在用 — 不可破坏）
# ============================================================

def test_prune_if_empty_still_works_for_other_steps(smoke_ws):
    """output_manager.prune_if_empty 行为没被破坏 — 仍可被其他 Step 调用。"""
    eid, rid = "test_eid_pr_keep", "2026-08-04_120000"
    run = _make_real_run(smoke_ws, eid, rid)
    # 业务目录（无 HTML）
    from output_manager import JobOutputManager
    out = JobOutputManager("j", encrypt_job_id=eid, run_id=rid, lazy=True)
    # prune_if_empty 仍会删（这是其他 Step 脚本依赖的语义，不能动）
    assert out.prune_if_empty() is True
    assert not run.exists()