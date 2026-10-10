# -*- coding: utf-8 -*-
"""强制 Windows 下 Python 脚本用 UTF-8 输出。

import 时自动 apply，不需要手动调用。

为什么需要：
    Windows PowerShell 默认 codepage 是 GBK (cp936)。
    Python 默认根据系统 codepage 写 stdout。
    如果 Python 强制 UTF-8 写 → UTF-8 字节 → PowerShell 用 GBK 解码 → 乱码。

本模块把 sys.stdout / sys.stderr 强制包成 UTF-8 TextIOWrapper，
所有后续 print / print(f"...{chinese}...") 都按 UTF-8 写出。

用法（必须在 import 任何其他模块前）：
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'shared'))
    import fix_encoding  # noqa
"""
import sys
import io


def apply():
    """在 Windows 下强制 stdout/stderr 用 UTF-8。"""
    if sys.platform != "win32":
        return
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        if stream is None:
            continue
        enc = getattr(stream, "encoding", "") or ""
        if enc.lower().startswith("utf"):
            continue
        buffer = getattr(stream, "buffer", None)
        if buffer is None:
            continue
        new_stream = io.TextIOWrapper(
            buffer, encoding="utf-8", errors="replace", line_buffering=True
        )
        setattr(sys, name, new_stream)


apply()
