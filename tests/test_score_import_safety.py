# -*- coding: utf-8 -*-
"""3 个评分脚本的 import 副作用测试（2026-08-03 新增）。

要求：3 个脚本的 stdout reconfigure 必须在 if __name__ == "__main__" 防护内。
被 import 时**不应**修改 sys.stdout / sys.stderr / sys.stdin。

如果违规：pytest 9.x capture 会抛 ValueError（已在本仓库第一轮 commit 1 出现过
score_resumes.py 同样的问题）。
"""
from __future__ import annotations
import io
import sys

import pytest


def _import_module(path: str):
    """用 importlib.util.spec_from_file_location 加载脚本（不走 package import）。"""
    import importlib.util
    spec = importlib.util.spec_from_file_location("mod_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_prepare_does_not_replace_stdout_on_import(tmp_path):
    sys.path.insert(0, str(tmp_path / "_unused"))  # ensure clean
    original_stdout = sys.stdout
    _import_module("resume-screener/scripts/prepare_scoring_inputs.py")
    assert sys.stdout is original_stdout, (
        "prepare_scoring_inputs.py 在模块顶层替换 sys.stdout —— "
        "import 时不应有副作用。把 if __name__ == \"__main__\" 防护外的代码挪进去。"
    )


def test_collect_does_not_replace_stdout_on_import(tmp_path):
    original_stdout = sys.stdout
    _import_module("resume-screener/scripts/collect_llm_scores.py")
    assert sys.stdout is original_stdout, (
        "collect_llm_scores.py 在模块顶层替换 sys.stdout —— "
        "import 时不应有副作用。"
    )


def test_score_resumes_does_not_replace_stdout_on_import(tmp_path):
    original_stdout = sys.stdout
    _import_module("resume-screener/scripts/score_resumes.py")
    assert sys.stdout is original_stdout, (
        "score_resumes.py 在模块顶层替换 sys.stdout。"
    )
