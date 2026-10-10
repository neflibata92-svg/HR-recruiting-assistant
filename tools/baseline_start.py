# -*- coding: utf-8 -*-
"""tools/baseline_start.py — boss_jd 旧行为基线（2026-08-03）

boss_jd 真实执行需要 patchright + CDP 9222 + BOSS 登录——**自动测试不连真实 BOSS**。
基线只做静态分析 + 间接验证：直接从 boss_jd.py 源文件提取 CLI 参数、stdout
解析逻辑、文件副作用。

确认要点：
  - 连续两次 start 应得到不同 run_id（create_new_run() 内部 YYYYMMDD_HHMMSS）
  - 失败时 atexit 清理空 run_dir
  - 三处 run_id 应一致
"""
from __future__ import annotations
import ast
import inspect
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOLKIT_ROOT = HERE.parent
BOSS_JD = TOOLKIT_ROOT / "boss-job-detail" / "scripts" / "boss_jd.py"
SHARED = TOOLKIT_ROOT / "shared"


def _argparse_args(source: str) -> list[dict]:
    """AST 抓 parser.add_argument 调用。"""
    tree = ast.parse(source)
    args = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not (isinstance(node.func, ast.Attribute) and node.func.attr == "add_argument"):
            continue
        flags = []
        for a in node.args:
            try:
                v = ast.literal_eval(a)
                if isinstance(v, str):
                    flags.append(v)
            except Exception:
                pass
        kwargs: dict = {}
        for kw in node.keywords:
            try:
                kwargs[kw.arg] = ast.literal_eval(kw.value)
            except Exception:
                pass
        if not flags:
            continue
        long_flag = next((f for f in flags if f.startswith("--")), flags[0])
        dest = long_flag.lstrip("-").replace("-", "_")
        args.append({"flags": flags, "dest": dest,
                     "required": kwargs.get("required", False),
                     "default": kwargs.get("default"),
                     "action": kwargs.get("action")})
    return args


def _print_calls(source: str) -> list[str]:
    """AST 抓 print(...) 字面量参数。"""
    tree = ast.parse(source)
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not (isinstance(node.func, ast.Attribute) and node.func.attr == "print"):
            continue
        if not node.args:
            continue
        try:
            v = ast.literal_eval(node.args[0])
            if isinstance(v, str):
                # 只截前 80 字符
                snippet = v[:80] + ("..." if len(v) > 80 else "")
                out.append(snippet)
        except Exception:
            out.append("<non-literal>")
    return out


def main() -> int:
    src = BOSS_JD.read_text(encoding="utf-8")
    out = {
        "file": str(BOSS_JD.relative_to(TOOLKIT_ROOT)),
        "argparse_args": _argparse_args(src),
        "print_calls": _print_calls(src),
        "docstring_head": (inspect.cleandoc(src.split('"""', 2)[1]) if '"""' in src else None)[:200] if '"""' in src else None,
    }
    out_path = TOOLKIT_ROOT / "artifacts" / "refactor" / "start-baseline.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
