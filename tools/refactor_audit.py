"""_audit.py — 全仓库代码审计（2026-08-03）

输入：boss-hr-agent-toolkit 仓库根目录
输出：_audit_output.json（机器可读 + 给人看的审计清单）

不执行被审计脚本的 main()，只读取 + 静态分析。
"""
from __future__ import annotations
import ast
import json
import os
import re
from pathlib import Path

# 工具包根目录 = tools/ 的父目录
REPO_ROOT = Path(__file__).resolve().parent.parent

# 我们关心的脚本（排除 tests/、conftest）
TARGETS = [
    "boss-job-detail/scripts/boss_jd.py",
    "boss-recommend-downloader/scripts/recommend_list.py",
    "boss-recommend-downloader/scripts/recommend_download.py",
    "resume-screener/scripts/prepare_scoring_inputs.py",
    "resume-screener/scripts/collect_llm_scores.py",
    "resume-screener/scripts/score_resumes.py",
    "html-report/scripts/generate_html_report.py",
    "boss-hr-greet/scripts/auto_greet.py",
    "shared/confirm_run.py",
    "shared/cli_runner.py",
    "shared/run_orchestrator.py",
    "shared/output_manager.py",
    "shared/job_registry.py",
    "shared/cdp_preflight.py",
    "shared/recruiter_job_catalog.py",
    "shared/human_interaction.py",
    "shared/job_resume_store.py",
    "shared/fix_encoding.py",
]


def _safe_name(name: str) -> str:
    return re.sub(r'[^A-Za-z0-9._~+-]', '_', name).strip()


def _first_line_docstring(tree: ast.AST) -> str | None:
    return ast.get_docstring(tree)


def analyze(path: Path) -> dict:
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src, filename=str(path))

    funcs: list[dict] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            args_list = [a.arg for a in node.args.args]
            defaults = node.args.defaults
            params = []
            offset = len(args_list) - len(defaults)
            for i, name in enumerate(args_list):
                d = ast.unparse(defaults[i - offset]) if i >= offset else None
                params.append({"name": name, "default": d, "required": i < offset})
            returns = ast.unparse(node.returns) if node.returns else None
            doc = ast.get_docstring(node)
            funcs.append({
                "name": node.name,
                "args": args_list,
                "params": params,
                "returns": returns,
                "doc": (doc.splitlines()[0] if doc else None),
            })

    main_func = next((f for f in funcs if f["name"] == "main"), None)
    has_main_block = '__main__' in src
    # 顶层 main() 函数 或 __main__ 块，都算 CLI 入口
    module_entry = "main()" if main_func else ("__main__ block" if has_main_block else None)
    module_doc = _first_line_docstring(tree)

    # argparse：找 parser.add_argument 调用，提取 dest / required / default
    argparse_args: list[dict] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not (isinstance(node.func, ast.Attribute) and node.func.attr == "add_argument"):
            continue
        # 至少 1 个位置参数是 flags（"--xxx" / "query"）
        flags = [ast.literal_eval(a) for a in node.args if isinstance(a, ast.Constant) and isinstance(a.value, str)]
        kwargs: dict = {}
        for kw in node.keywords:
            try:
                kwargs[kw.arg] = ast.literal_eval(kw.value)
            except Exception:
                kwargs[kw.arg] = ast.unparse(kw.value)
        argparse_args.append({
            "flags": flags,
            "required": kwargs.get("required", False),
            "default": kwargs.get("default"),
            "type": kwargs.get("type"),
            "action": kwargs.get("action"),
        })

    # 退出码：搜 SystemExit(N) / raise SystemExit(N) / sys.exit(N) / exit_code=N
    exit_codes: set[int] = set()
    for m in re.finditer(r'SystemExit\((\d+)\)', src):
        exit_codes.add(int(m.group(1)))
    for m in re.finditer(r'sys\.exit\((\d+)\)', src):
        exit_codes.add(int(m.group(1)))
    for m in re.finditer(r'"exit_code"\s*:\s*(\d+)', src):
        exit_codes.add(int(m.group(1)))

    # import 副作用
    import_side_effects: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for n in node.names:
                import_side_effects.append(f"import {n.name}")
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                import_side_effects.append(f"from {node.module} import " + ", ".join(n.name for n in node.names))
    # 检查 stdout 重写
    if re.search(r'sys\.stdout\s*=', src) or re.search(r'sys\.stdout\.reconfigure', src):
        import_side_effects.append("⚠️ sys.stdout reconfigure / 替换（pytest 兼容性问题）")

    # 路径依赖：找 ~/Desktop、jobs.json、runs/、state/、process/、scoring/ 等字面量
    path_literals = list(set(re.findall(r'~?/?(?:Desktop/[^"\']+|jobs\.json|runs?/[^"\']*|state/[^"\']*|process/[^"\']*|scoring/[^"\']*|batch_\d+[^"\']*)', src)))

    return {
        "file": str(path.relative_to(REPO_ROOT)),
        "module_doc": (module_doc or "").splitlines()[0] if module_doc else None,
        "top_level_funcs": [f["name"] for f in funcs],
        "func_details": [
            {k: v for k, v in f.items() if k != "doc"}
            for f in funcs if not f["name"].startswith("_")
        ],
        "main_func": main_func["name"] if main_func else None,
        "module_entry": module_entry,
        "argparse": argparse_args,
        "exit_codes": sorted(exit_codes),
        "exit_code_in_json": sorted({int(m.group(1)) for m in re.finditer(r'"exit_code"\s*:\s*(\d+)', src)}),
        "imports": import_side_effects,
        "path_literals": path_literals,
        "lines": src.count("\n") + 1,
    }


def main() -> int:
    out = {"repo": str(REPO_ROOT), "scripts": []}
    for rel in TARGETS:
        path = REPO_ROOT / rel
        if not path.exists():
            continue
        out["scripts"].append(analyze(path))
    out_path = REPO_ROOT / "artifacts" / "refactor" / "_audit_output.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {out_path}  ({len(out['scripts'])} scripts)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
