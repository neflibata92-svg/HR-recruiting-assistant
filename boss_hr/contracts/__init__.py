"""boss_hr.contracts — 统一结果/错误契约。

status / report / confirm / score / fetch / start / greet 共用同一套
结构化结果，不允许各命令自带 JSON 字段语义。
"""
from .results import CommandResult, ok, error
from .errors import ExitCode, ErrorCode, error_from_subprocess_rc

__all__ = [
    "CommandResult", "ok", "error",
    "ExitCode", "ErrorCode", "error_from_subprocess_rc",
]
