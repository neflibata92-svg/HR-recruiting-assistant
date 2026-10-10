# -*- coding: utf-8 -*-
"""auto_greet.maybe_finish 测试（2026-08-04）。

修复背景：之前 orch.finish() 缺 run_id（签名要求必填），抛 TypeError
被 except Exception 吞掉，run.json.finished 恒为 false — 文档声称的
"招呼成功 ≥1 自动 finish()" 实际从未生效。

测试覆盖（用户 §二.5 要求）：
  1. greeted=0 → 不 finish
  2. greeted=1, !dry, !no_finish → finish(run_id=run_id) 且 finished=true
  3. dry_run=True → 不 finish
  4. no_finish=True → 不 finish
  5. finish 异常不静默（必须向上抛）
  6. 不修改其他 run（mock orch 只接收到一个 run_id）
  7. 静态审计：auto_greet.py 不再"无 run_id 实参"调 finish
  8. 静态审计：maybe_finish 函数必须存在
"""
from __future__ import annotations
import ast
import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest


_HERE = Path(__file__).resolve().parent
_TOOLKIT_ROOT = _HERE.parent
_AUTO_GREET = _TOOLKIT_ROOT / "boss-hr-greet" / "scripts" / "auto_greet.py"


@pytest.fixture
def auto_greet_module():
    sys.path.insert(0, str(_TOOLKIT_ROOT / "boss-hr-greet" / "scripts"))
    sys.path.insert(0, str(_TOOLKIT_ROOT / "shared"))
    return __import__("auto_greet")


# ============================================================
# 1-4: maybe_finish 决策矩阵
# ============================================================

def test_maybe_finish_greeted_zero_does_not_finish(auto_greet_module):
    """greeted=0 → 不 finish。"""
    orch = MagicMock()
    out = auto_greet_module.maybe_finish(orch, "rid_x", greeted_count=0)
    assert out is False
    orch.finish.assert_not_called()


def test_maybe_finish_greeted_one_calls_finish_with_run_id(auto_greet_module):
    """greeted=1, !dry, !no_finish → finish(run_id=rid) 且返回 True。"""
    orch = MagicMock()
    out = auto_greet_module.maybe_finish(
        orch, "rid_x", greeted_count=1,
        dry_run=False, no_finish=False,
    )
    assert out is True
    orch.finish.assert_called_once_with(run_id="rid_x")


def test_maybe_finish_dry_run_does_not_finish(auto_greet_module):
    """dry_run=True → 不 finish（即使 greeted=1）。"""
    orch = MagicMock()
    out = auto_greet_module.maybe_finish(
        orch, "rid_x", greeted_count=3,
        dry_run=True, no_finish=False,
    )
    assert out is False
    orch.finish.assert_not_called()


def test_maybe_finish_no_finish_flag_does_not_finish(auto_greet_module):
    """no_finish=True → 不 finish（即使 greeted=1）。"""
    orch = MagicMock()
    out = auto_greet_module.maybe_finish(
        orch, "rid_x", greeted_count=2,
        dry_run=False, no_finish=True,
    )
    assert out is False
    orch.finish.assert_not_called()


def test_maybe_finish_negative_count_does_not_finish(auto_greet_module):
    """greeted<0（异常输入）→ 不 finish。"""
    orch = MagicMock()
    out = auto_greet_module.maybe_finish(orch, "rid_x", greeted_count=-1)
    assert out is False
    orch.finish.assert_not_called()


# ============================================================
# 5: finish 异常不静默
# ============================================================

def test_maybe_finish_propagates_finish_exception(auto_greet_module):
    """orch.finish 失败时，异常必须向上抛（不静默伪装成功）。"""
    orch = MagicMock()
    orch.finish.side_effect = RuntimeError("run 不存在")
    with pytest.raises(RuntimeError, match="run 不存在"):
        auto_greet_module.maybe_finish(orch, "rid_x", greeted_count=1)
    # 也调过了（不是被吞）
    orch.finish.assert_called_once_with(run_id="rid_x")


def test_maybe_finish_propagates_type_error_on_signature_mismatch(auto_greet_module):
    """finish 签名若再被破坏（TypeError），也必须可见。"""
    orch = MagicMock()
    orch.finish.side_effect = TypeError("missing 1 required argument: 'run_id'")
    with pytest.raises(TypeError, match="run_id"):
        auto_greet_module.maybe_finish(orch, "rid_x", greeted_count=1)


# ============================================================
# 6: 不修改其他 run（用真实 run.json 验证）
# ============================================================

def test_maybe_finish_only_targets_explicit_run_id(auto_greet_module, tmp_path, monkeypatch):
    """maybe_finish 只把 run_id 传给 orch.finish，绝不读 / 写其他 run。"""
    import output_manager
    monkeypatch.setattr(output_manager, "OUTPUT_ROOT", str(tmp_path), raising=False)

    # 两个 run 目录 + run.json
    target_eid, target_rid = "test_eid_f1", "2026-08-04_120000"
    other_eid, other_rid = "test_eid_f1", "2026-08-03_170000"
    for eid, rid in [(target_eid, target_rid), (other_eid, other_rid)]:
        run = tmp_path / eid / "runs" / rid
        run.mkdir(parents=True)
        (run / "run.json").write_text(json.dumps({
            "run_id": rid, "encrypt_job_id": eid,
            "confirmed": True, "finished": False,
        }), encoding="utf-8")

    # 用真实 RunOrchestrator（不 mock）— 验证 finish 真把 run.json.finished 改 true，
    # 且只动 target
    from run_orchestrator import RunOrchestrator
    orch = RunOrchestrator("j", encrypt_job_id=target_eid)

    finished = auto_greet_module.maybe_finish(
        orch, target_rid, greeted_count=1,
    )
    assert finished is True

    # target.run.json.finished = true
    target_run = json.loads(
        (tmp_path / target_eid / "runs" / target_rid / "run.json").read_text(encoding="utf-8"))
    assert target_run["finished"] is True

    # other.run.json.finished 仍 false
    other_run = json.loads(
        (tmp_path / other_eid / "runs" / other_rid / "run.json").read_text(encoding="utf-8"))
    assert other_run["finished"] is False


# ============================================================
# 7-8: 静态审计
# ============================================================

def test_auto_greet_source_no_bare_orch_finish_call():
    """AST 静态审计：auto_greet.py 不再 'orch.finish()'（无参）— 必带 run_id。"""
    src = _AUTO_GREET.read_text(encoding="utf-8")
    tree = ast.parse(src)

    bad_calls: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        target = node.func
        if not isinstance(target, ast.Attribute):
            continue
        if ast.unparse(target) != "orch.finish":
            continue
        # orch.finish(<args>) — 任何调用都应带 run_id
        kwargs = {kw.arg for kw in node.keywords}
        if "run_id" not in kwargs:
            arg_names = [ast.unparse(a) for a in node.args]
            bad_calls.append((node.lineno, f"orch.finish({', '.join(arg_names)})"))

    assert bad_calls == [], (
        f"auto_greet.py 中 orch.finish() 必须传 run_id: {bad_calls}"
    )


def test_auto_greet_source_has_maybe_finish_function():
    """模块级函数 maybe_finish 必须存在。"""
    src = _AUTO_GREET.read_text(encoding="utf-8")
    tree = ast.parse(src)
    func_names = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
    assert "maybe_finish" in func_names


def test_auto_greet_source_no_swallowed_finish_exception():
    """auto_greet.py 主流程里不再 'except Exception' 吞 finish 错。"""
    src = _AUTO_GREET.read_text(encoding="utf-8")
    tree = ast.parse(src)

    # 找到 maybe_finish 函数；except Exception 出现在其他地方 OK（如 note_skip_if_unsaved），
    # 但不能出现在 maybe_finish 内部。
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "maybe_finish":
            for sub in ast.walk(node):
                if isinstance(sub, ast.ExceptHandler) and sub.type is not None:
                    tname = ast.unparse(sub.type)
                    assert tname != "Exception", (
                        f"maybe_finish 内部不应 except Exception 吞错（line {sub.lineno}）"
                    )


def test_auto_greet_source_documents_finish_fix():
    """修复说明应在源文件里。"""
    src = _AUTO_GREET.read_text(encoding="utf-8")
    assert "run_id" in src
    # maybe_finish 函数里应有 2026-08-04 修复说明
    idx = src.find("def maybe_finish")
    window = src[idx: idx + 1500]
    assert "2026-08-04" in window
    assert ("不静默" in window) or ("向上抛" in window) or ("TypeError" in window)