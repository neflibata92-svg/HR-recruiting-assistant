# -*- coding: utf-8 -*-
"""
cli_runner.py — 项目内 Python CLI 安全执行层（2026-07-30）。

设计动机：
  Windows PowerShell/CMD 对中文、空格、JSON、特殊字符的参数解析不稳定。
  本 runner 用 subprocess.run([...], shell=False) + 参数数组，
  保证中文 / 空格 / JSON 字符串作为**一个完整参数**传给子进程。

Runner 不是流程编排器：

  - ❌ 不创建 run_id
  - ❌ 不选择 run_id
  - ❌ 不读 current_run.json
  - ❌ 不自动补 --run-id
  - ❌ 不自动 confirm_run
  - ❌ 不搜索桌面 / 历史 run 的旧文件
  - ❌ 不连续执行完整流程
  - ❌ 不替代 RunOrchestrator
  - ❌ 不替代业务脚本的 argparse + 状态校验

  Runner 是执行器，只负责：
  - ✅ 用 sys.executable 启动指定的项目内 CLI
  - ✅ 用参数数组传参
  - ✅ subprocess.run(..., shell=False)
  - ✅ 设置 Python UTF-8 环境
  - ✅ 固定 cwd 到工具包根目录
  - ✅ 捕获 stdout / stderr / 真实退出码
  - ✅ 统一 JSON 输出
  - ✅ 保留子进程退出码

用法（Python API）：
    from shared.cli_runner import run_python_cli
    result = run_python_cli(
        "score_resumes",
        [
            "--job-name", "结构设计、研发工程师",
            "--encrypt-job-id", "DemoJobId000000000000000000001",
            "--run-id", "2026-07-30_132000",
        ],
        timeout=600,
    )
    print(result.returncode)
    print(result.stdout)

用法（CLI via --spec-file）：
    {
      "tool": "score_resumes",
      "args": ["--job-name", "...", "--encrypt-job-id", "...", "--run-id", "..."],
      "timeout": 600,
      "check": false
    }

    python -X utf8 shared/cli_runner.py --spec-file spec.json
"""
from __future__ import annotations
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Sequence


# ---------- 工具包根目录 ----------
# cli_runner.py 位于 shared/cli_runner.py
# 工具包根 = shared/ 的父目录
TOOLKIT_ROOT: Path = Path(__file__).resolve().parent.parent


# ---------- 工具白名单 ----------
# 路径相对 TOOLKIT_ROOT。禁止 ../ 逃逸，禁止白名单外的任意路径。
TOOLS: dict[str, str] = {
    "boss_jd":             "boss-job-detail/scripts/boss_jd.py",
    "confirm_run":         "shared/confirm_run.py",
    "recommend_list":      "boss-recommend-downloader/scripts/recommend_list.py",
    "recommend_download":  "boss-recommend-downloader/scripts/recommend_download.py",
    "score_resumes":       "resume-screener/scripts/score_resumes.py",
    "generate_html_report": "html-report/scripts/generate_html_report.py",
    "auto_greet":          "boss-hr-greet/scripts/auto_greet.py",
    # 2026-07-31 新增：简历净化层（在 score_resumes 之前跑，把 new_resumes.json
    # 拆成每人一文件的精简评分输入）
    "prepare_scoring_inputs": "resume-screener/scripts/prepare_scoring_inputs.py",
    # 2026-07-31 新增：LLM 评分合并器（把 scoring/outputs/candidate_*.json 合并成
    # _llm_scores.json 供 score_resumes.py 使用）
    "collect_llm_scores": "resume-screener/scripts/collect_llm_scores.py",
}


# ---------- 自定义异常 ----------
class CliRunnerError(Exception):
    """cli_runner 调用的子进程退出码非 0 时抛出（仅当 check=True 时）。"""

    def __init__(self, tool: str, returncode: int, stdout: str, stderr: str):
        self.tool = tool
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        super().__init__(
            f"cli_runner 调用 '{tool}' 失败：returncode={returncode}, "
            f"stderr={stderr[:200]}"
        )


# ---------- 内部：解析白名单 + 路径安全 ----------
def _resolve_tool(tool: str) -> Path:
    """根据 tool 名解析绝对路径。校验：

    - tool 必须在 TOOLS 白名单中
    - 解析后的路径必须存在
    - 解析后的路径必须位于 TOOLKIT_ROOT 内（防止 ../ 逃逸）
    """
    if not isinstance(tool, str) or not tool:
        raise ValueError(
            f"tool 必须是非空字符串；收到 {tool!r}。"
            f"允许的工具：{sorted(TOOLS.keys())}"
        )
    if tool not in TOOLS:
        raise ValueError(
            f"tool={tool!r} 不在白名单中。"
            f"允许的工具：{sorted(TOOLS.keys())}"
        )
    rel = TOOLS[tool]
    # 解析为绝对路径
    script_path = (TOOLKIT_ROOT / rel).resolve()
    # 防 ../ 逃逸：resolved 必须在 TOOLKIT_ROOT 内
    try:
        script_path.relative_to(TOOLKIT_ROOT)
    except ValueError:
        raise ValueError(
            f"tool={tool!r} 路径逃逸工具包根目录：{script_path}。"
            f"白名单路径必须位于 {TOOLKIT_ROOT} 内。"
        )
    if not script_path.is_file():
        raise FileNotFoundError(
            f"tool={tool!r} 对应脚本不存在：{script_path}"
        )
    return script_path


# ---------- 内部：构造环境变量 ----------
def _build_env() -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONHOME"] = ""  # 与原文档一致；Windows cmd 兼容
    return env


# ---------- Python API ----------
def run_python_cli(
    tool: str,
    args: Sequence[str],
    *,
    timeout: float | None = None,
    check: bool = False,
) -> subprocess.CompletedProcess[str]:
    """安全执行白名单内的项目 CLI。

    Args:
        tool: 白名单工具名（TOOLS 的 key）
        args: 传给子脚本的完整参数列表（每一项已是完整字符串，不拆分）
        timeout: 超时秒数；None 表示无超时
        check: True 时子进程返回非 0 → 抛 CliRunnerError；False 时总是返回 CompletedProcess

    Returns:
        subprocess.CompletedProcess[str]，含 stdout/stderr/returncode

    Raises:
        ValueError: tool 不在白名单 / args 类型不对 / 路径逃逸
        FileNotFoundError: 脚本不存在
        CliRunnerError: check=True 且子进程返回非 0 时
    """
    # 1. 解析白名单
    script_path = _resolve_tool(tool)

    # 2. args 类型校验
    if not isinstance(args, (list, tuple)):
        raise ValueError(
            f"args 必须是字符串 list/tuple；收到 {type(args).__name__}"
        )
    args_list = [str(a) for a in args]

    # 3. 构造完整命令数组（绝不 " ".join！）
    cmd = [sys.executable, "-X", "utf8", str(script_path), *args_list]

    # 4. 执行
    kwargs: dict[str, Any] = dict(
        args=cmd,
        shell=False,                # 关键：禁止 shell 解析
        cwd=str(TOOLKIT_ROOT),      # 固定 cwd 到工具包根
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=_build_env(),
    )
    if timeout is not None:
        kwargs["timeout"] = timeout

    return subprocess.run(**kwargs)


# ---------- CLI 入口：--spec-file ----------
def _validate_spec(spec: Any) -> dict[str, Any]:
    """校验 spec JSON 结构：tool/args/timeout/check 类型必须正确。"""
    if not isinstance(spec, dict):
        raise ValueError(f"spec 必须是 JSON object，实际={type(spec).__name__}")
    tool = spec.get("tool")
    if not isinstance(tool, str) or not tool:
        raise ValueError("spec.tool 必须是非空字符串")
    args = spec.get("args", [])
    if not isinstance(args, list):
        raise ValueError(f"spec.args 必须是 list，实际={type(args).__name__}")
    for i, a in enumerate(args):
        if not isinstance(a, str):
            raise ValueError(
                f"spec.args[{i}] 必须是字符串，实际={type(a).__name__}: {a!r}"
            )
    timeout = spec.get("timeout")
    if timeout is not None and not isinstance(timeout, (int, float)):
        raise ValueError(f"spec.timeout 必须是数字或 null，实际={type(timeout).__name__}")
    check = spec.get("check", False)
    if not isinstance(check, bool):
        raise ValueError(f"spec.check 必须是 bool，实际={type(check).__name__}")
    return {"tool": tool, "args": args, "timeout": timeout, "check": check}


def _emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False))


def main(argv: Sequence[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(
        description="项目内 Python CLI 安全执行层。"
                    "Runner 不创建/选择/确认 run，只负责用参数数组启动白名单内的 CLI。"
                    "Step 1 后必须停止；用户确认后才能继续 Step 2。",
    )
    parser.add_argument(
        "--spec-file", required=True,
        help="【必填】UTF-8 JSON spec 文件路径。"
             "spec 包含 tool / args / timeout / check。",
    )
    args = parser.parse_args(argv)

    # 1. 读取 spec
    try:
        with open(args.spec_file, "r", encoding="utf-8") as f:
            spec_raw = json.load(f)
    except FileNotFoundError as e:
        _emit({"status": "error", "message": f"spec 文件不存在：{e}"})
        return 1
    except json.JSONDecodeError as e:
        _emit({"status": "error", "message": f"spec 不是合法 JSON：{e}"})
        return 1

    # 2. 校验 spec 结构
    try:
        spec = _validate_spec(spec_raw)
    except ValueError as e:
        _emit({"status": "error", "message": str(e)})
        return 1

    # 3. 执行
    try:
        result = run_python_cli(
            tool=spec["tool"],
            args=spec["args"],
            timeout=spec["timeout"],
            check=spec["check"],
        )
    except (ValueError, FileNotFoundError) as e:
        _emit({"status": "error", "message": str(e)})
        return 1
    except CliRunnerError as e:
        _emit({
            "status": "failed",
            "tool": e.tool,
            "returncode": e.returncode,
            "stdout": e.stdout,
            "stderr": e.stderr,
        })
        return e.returncode
    except subprocess.TimeoutExpired as e:
        _emit({
            "status": "timeout",
            "tool": spec["tool"],
            "returncode": -1,
            "stdout": e.stdout.decode("utf-8", errors="replace") if e.stdout else "",
            "stderr": (e.stderr.decode("utf-8", errors="replace") if e.stderr else ""),
        })
        return 124  # 与 GNU timeout 约定一致

    # 4. 统一 JSON 输出
    _emit({
        "status": "success" if result.returncode == 0 else "failed",
        "tool": spec["tool"],
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    })
    # 5. runner 退出码 = 子进程退出码（不归一化）
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())