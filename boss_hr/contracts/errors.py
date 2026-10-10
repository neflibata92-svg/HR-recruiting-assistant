"""boss_hr.contracts.errors — 统一退出码 + 错误码。

退出码语义：**保留旧脚本的退出码**（不归一化）。
- 0   - 成功
- 1   - 参数错误（通用）/ FileNotFoundError / ValueError 未捕获
- 2   - 缺 --run-id（argparse 默认）
- 20  - 用户未确认（confirm 前置守卫；recommend_list / recommend_download）
- 22  - 缺 --run-id（业务层防御；CLI 层 required 之后通常不会触发）
- 23  - run 不存在
- 24  - run 与岗位不匹配
- 26  - 缺输入文件（screening_inputs / _llm_scores.json）
- 27  - 缺输出/上游结果（screening_results.json）
- 99  - 内部错误（兜底）

error.code 是字符串枚举，给用户/智能体看的；与 ExitCode 数字不是 1-to-1
（多个语义可共用同一个 exit code，例如 RUN_NOT_FOUND 和 JOB_MISMATCH 都
用 EXIT_CODE_RUN_NOT_FOUND=23 / 24）。
"""
from __future__ import annotations
from dataclasses import dataclass
from enum import IntEnum, Enum
from typing import Optional


class ExitCode(IntEnum):
    OK = 0
    GENERIC = 1  # 参数错误通用（与第一轮 status 缺 eid 保持一致）
    MISSING_RUN_ID = 2
    AWAITING_CONFIRMATION = 20
    RUN_NOT_FOUND = 23
    RUN_JOB_MISMATCH = 24
    MISSING_INPUT = 26
    MISSING_OUTPUT = 27
    INTERNAL = 99


class ErrorCode(str, Enum):
    """统一错误码字符串（语义标签）。"""
    MISSING_ENCRYPT_JOB_ID = "MISSING_ENCRYPT_JOB_ID"
    MISSING_RUN_ID = "MISSING_RUN_ID"
    RUN_NOT_FOUND = "RUN_NOT_FOUND"
    JOB_MISMATCH = "JOB_MISMATCH"
    MISSING_SCREENING = "MISSING_SCREENING"
    AWAITING_CONFIRMATION = "AWAITING_CONFIRMATION"
    INTERNAL = "INTERNAL"
    UNKNOWN_COMMAND = "UNKNOWN_COMMAND"

    # v1.1.1 新增：浏览器环境 / 岗位实时解析
    EDGE_NOT_FOUND = "EDGE_NOT_FOUND"
    CDP_NOT_RUNNING = "CDP_NOT_RUNNING"
    CDP_CONNECT_FAILED = "CDP_CONNECT_FAILED"
    BOSS_LOGIN_REQUIRED = "BOSS_LOGIN_REQUIRED"
    BOSS_PAGE_REQUIRED = "BOSS_PAGE_REQUIRED"
    JOB_NOT_FOUND = "JOB_NOT_FOUND"
    JOB_AMBIGUOUS = "JOB_AMBIGUOUS"
    JOB_ID_MISMATCH = "JOB_ID_MISMATCH"
    EDGE_LAUNCH_FAILED = "EDGE_LAUNCH_FAILED"


@dataclass(frozen=True)
class UnifiedError:
    """统一错误对象（含给用户看的 code/message + 给调试看的子进程 rc）。"""
    code: ErrorCode
    message: str
    subprocess_returncode: Optional[int] = None
    recoverable: Optional[bool] = None  # v1.1.1: True 表示有可执行恢复路径

    def to_dict(self) -> dict:
        out: dict = {"code": self.code.value, "message": self.message}
        if self.subprocess_returncode is not None:
            out["subprocess_returncode"] = self.subprocess_returncode
        if self.recoverable is not None:
            out["recoverable"] = self.recoverable
        return out


# 子脚本退出码 → 统一 (ExitCode, ErrorCode, 默认 message)
_SUBPROCESS_RC_MAP: dict[int, tuple[ExitCode, ErrorCode, str]] = {
    0:  (ExitCode.OK, ErrorCode.INTERNAL, "不应该映射 rc=0"),
    1:  (ExitCode.INTERNAL, ErrorCode.INTERNAL, "子进程失败（rc=1）"),
    2:  (ExitCode.MISSING_RUN_ID, ErrorCode.MISSING_RUN_ID, "子脚本 argparse 缺 --run-id"),
    20: (ExitCode.AWAITING_CONFIRMATION, ErrorCode.AWAITING_CONFIRMATION,
         "run 尚未用户确认，禁止执行"),
    22: (ExitCode.MISSING_RUN_ID, ErrorCode.MISSING_RUN_ID, "子脚本缺 --run-id"),
    23: (ExitCode.RUN_NOT_FOUND, ErrorCode.RUN_NOT_FOUND, "run_id 不存在"),
    24: (ExitCode.RUN_JOB_MISMATCH, ErrorCode.JOB_MISMATCH, "run 与岗位不匹配"),
    26: (ExitCode.MISSING_INPUT, ErrorCode.INTERNAL, "子进程缺输入文件"),
    27: (ExitCode.MISSING_OUTPUT, ErrorCode.MISSING_SCREENING, "缺 screening_results.json"),
}


def error_from_subprocess_rc(rc: int, *, default_message: str | None = None) -> UnifiedError:
    """子进程退出码 → UnifiedError。"""
    if rc in _SUBPROCESS_RC_MAP:
        exit_code, err_code, default_msg = _SUBPROCESS_RC_MAP[rc]
        return UnifiedError(code=err_code, message=default_msg,
                             subprocess_returncode=rc)
    return UnifiedError(
        code=ErrorCode.INTERNAL,
        message=default_message or f"未知子进程退出码 {rc}",
        subprocess_returncode=rc,
    )


__all__ = ["ExitCode", "ErrorCode", "UnifiedError", "error_from_subprocess_rc"]
