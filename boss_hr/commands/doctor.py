# -*- coding: utf-8 -*-
"""boss_hr.commands.doctor — `boss-hr doctor` 命令处理。

`boss-hr doctor` 是环境健康检查 + 启动辅助命令。

  boss-hr doctor
  boss-hr doctor --launch-browser

不连业务岗位接口，不创建 run，不写业务输出。
"""
from __future__ import annotations
import argparse

from boss_hr.contracts.results import CommandResult
from boss_hr.application.doctor_service import run_doctor


def add_arguments(parser: argparse.ArgumentParser) -> None:
    """doctor 不要求 --job-name / --run-id / --encrypt-job-id。"""
    parser.add_argument(
        "--launch-browser", "--launch-edge", dest="launch_edge", action="store_true",
        help="启动专用浏览器（macOS 为 Chrome，Windows 为 Edge），并等待 CDP 端口监听",
    )
    parser.add_argument(
        "--skip-browser", action="store_true",
        help="只跑本地检查（Python 版本 / patchright），不连 CDP",
    )


def run(args: argparse.Namespace) -> CommandResult:
    return run_doctor(
        launch_edge_flag=bool(getattr(args, "launch_edge", False)),
        skip_browser=bool(getattr(args, "skip_browser", False)),
    )


__all__ = ["add_arguments", "run"]
