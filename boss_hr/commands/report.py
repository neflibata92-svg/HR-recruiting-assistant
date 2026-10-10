# -*- coding: utf-8 -*-
"""boss_hr.commands.report — report 命令处理。"""
from __future__ import annotations
import argparse

from boss_hr.contracts.results import CommandResult
from boss_hr.application.report_service import generate_report
from boss_hr.commands._argparse_helpers import (
    add_required_arguments, require_encrypt_job_id,
)


def add_arguments(parser: argparse.ArgumentParser) -> None:
    add_required_arguments(parser)


def run(args: argparse.Namespace) -> CommandResult:
    eid = require_encrypt_job_id(args._parser, args)
    return generate_report(
        job_name=args.job_name,
        encrypt_job_id=eid,
        run_id=args.run_id,
    )


__all__ = ["add_arguments", "run"]
