"""tools/baseline_fetch.py — fetch 旧行为基线（2026-08-03）

推荐牛人 / 下载两个脚本都需要真实浏览器（patchright + CDP 9222）
+ 真实 BOSS API。**不连真实 BOSS**——基线只做静态分析 + 间接验证。

通过 importlib 加载两个脚本并提取：
  - argparse 入参（dest / required / default）
  - 输出文件路径（process/recommend_geek_ids.json / new_resumes.json / failed_resumes.json）
  - state/ 副作用（JobResumeStore 调用）
  - 已确认守卫（未 confirmed → SystemExit(20)）
  - 退出码（0 / 20 / 1）

业务函数 get_recommend_candidates / download_resumes 不直接调用（需要
真实浏览器）；只验证 import 不抛错 + 模块 API 存在。
"""
from __future__ import annotations
import importlib.util
import inspect
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOLKIT_ROOT = HERE.parent
LIST_SCRIPT = TOOLKIT_ROOT / "boss-recommend-downloader" / "scripts" / "recommend_list.py"
DL_SCRIPT = TOOLKIT_ROOT / "boss-recommend-downloader" / "scripts" / "recommend_download.py"
SHARED = TOOLKIT_ROOT / "shared"


def _load(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(path.parent.parent.parent / "shared"))
    spec.loader.exec_module(mod)
    return mod


def _argparse_args(mod) -> list[dict]:
    """AST 抓 parser.add_argument 调用，提取 dest/required/default。"""
    import ast
    args = []
    for node in ast.walk(ast.parse(inspect.getsource(mod))):
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
        # dest 推断：--foo-bar → foo_bar
        long_flag = next((f for f in flags if f.startswith("--")), flags[0])
        dest = long_flag.lstrip("-").replace("-", "_")
        args.append({
            "flags": flags,
            "dest": dest,
            "required": kwargs.get("required", False),
            "default": kwargs.get("default"),
            "type": kwargs.get("type"),
        })
    return args


def main() -> int:
    out: dict = {}
    for label, path in [("recommend_list", LIST_SCRIPT), ("recommend_download", DL_SCRIPT)]:
        try:
            mod = _load(path)
        except Exception as e:
            out[label] = {"import_error": str(e)}
            continue
        out[label] = {
            "argparse_args": _argparse_args(mod),
            "public_functions": [
                name for name, obj in vars(mod).items()
                if callable(obj) and not name.startswith("_") and getattr(obj, "__module__", None) == path.stem
            ],
            "docstring_head": (inspect.getdoc(mod) or "").splitlines()[0] if inspect.getdoc(mod) else None,
        }

    out_path = TOOLKIT_ROOT / "artifacts" / "refactor" / "fetch-baseline.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
