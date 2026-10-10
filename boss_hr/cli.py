#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""boss-hr CLI — 统一入口。

分层（无行为变化重构后）：
  cli.py            ← 只注册 argparse + 调用 commands + emit JSON + 顶层 exit code
  commands/         ← CLI 参数 → application 请求
  application/      ← 状态校验 + 业务编排
  adapters/         ← shared.cli_runner / 子脚本 stdout 解析
  contracts/        ← 统一结果 / 退出码 / 错误对象

退出码语义：保留旧脚本的退出码（不归一化）。

JSON 输出 schema：
  status 命令保留第一轮 schema（status:"ok"/"blocked"/"error" + 顶层字段）
  report / confirm 等使用通用 schema（ok/data/next_action 或 ok=false + error）

用法：
  python -X utf8 boss_hr/cli.py status --job-name "<岗位>" \
      --encrypt-job-id "<id>" --run-id "<run_id>"
  python -X utf8 boss_hr/cli.py report --job-name "<岗位>" \
      --encrypt-job-id "<id>" --run-id "<run_id>"
  python -X utf8 boss_hr/cli.py confirm --job-name "<岗位>" \
      --encrypt-job-id "<id>" --run-id "<run_id>"
"""
from __future__ import annotations
import argparse
import json
import os
import sys

# 把工具包根 + shared/ 加进 sys.path；
# 必须放在 import boss_hr.* 之前（子进程 `python boss_hr/cli.py ...`
# 启动时 sys.path 默认不含 boss_hr 父目录）。
_HERE = os.path.dirname(os.path.abspath(__file__))
_TOOLKIT_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _TOOLKIT_ROOT)
sys.path.insert(0, os.path.join(_TOOLKIT_ROOT, "shared"))

from boss_hr.commands import status as status_cmd
from boss_hr.commands import report as report_cmd
from boss_hr.commands import confirm as confirm_cmd
from boss_hr.commands import score as score_cmd
from boss_hr.commands import fetch as fetch_cmd
from boss_hr.commands import start as start_cmd
from boss_hr.commands import greet as greet_cmd
from boss_hr.commands import doctor as doctor_cmd


def _emit(payload: dict, *, exit_code: int = 0) -> int:
    """统一 JSON 输出到 stdout。"""
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()
    return exit_code


def _log(msg: str) -> None:
    """日志写 stderr。"""
    sys.stderr.write(f"[boss_hr] {msg}\n")
    sys.stderr.flush()


def _run_command(command: str, result) -> int:
    """command handler 返回值 → emit + exit code。

    两种返回类型：
      - tuple[int, dict]：status 命令（保留旧 schema）
      - boss_hr.contracts.CommandResult：通用 schema
    """
    if isinstance(result, tuple):
        exit_code, payload = result
        return _emit(payload, exit_code=exit_code)
    return _emit(result.to_dict(command), exit_code=int(result.exit_code))


# commands 注册表：command name → (add_arguments_fn, run_fn)
COMMANDS = {
    "status": (status_cmd.add_arguments, status_cmd.run),
    "report": (report_cmd.add_arguments, report_cmd.run),
    "confirm": (confirm_cmd.add_arguments, confirm_cmd.run),
    "score": (score_cmd.add_arguments, score_cmd.run),
    "fetch": (fetch_cmd.add_arguments, fetch_cmd.run),
    "start": (start_cmd.add_arguments, start_cmd.run),
    "greet": (greet_cmd.add_arguments, greet_cmd.run),
    "doctor": (doctor_cmd.add_arguments, doctor_cmd.run),
}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="boss-hr",
        description="BOSS HR 工具包统一 CLI（v1.1+）。",
    )
    sub = p.add_subparsers(dest="command", required=True)
    for name, (add_args, _run_fn) in COMMANDS.items():
        sub_cmd = sub.add_parser(name, help=f"{name} 命令")
        add_args(sub_cmd)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    # argparse.Namespace 不持有 subparser 反向引用；commands 的
    # require_encrypt_job_id(parser, ns) 需要 parser 来调 .error() → rc=2。
    # 从 subparser action 拿到对应的子 parser 挂上。
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction) and args.command in action.choices:
            args._parser = action.choices[args.command]
            break
    else:
        args._parser = parser

    add_args_fn, run_fn = COMMANDS[args.command]
    result = run_fn(args)
    return _run_command(args.command, result)


if __name__ == "__main__":
    sys.exit(main())
