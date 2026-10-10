# -*- coding: utf-8 -*-
"""pytest 配置

解决 school_tier.py 在 import 时对 sys.stdout 的 re-wrap 与 pytest 捕获/输出系统的冲突。

策略：在 conftest 加载阶段（早于任何测试代码 import），把 sys.stdout.encoding
置为 "utf-8"。这样 school_tier.py 里的 re-wrap 条件（`startswith("utf")`）
不成立，re-wrap 会被跳过，pytest 的捕获/输出就安全。

⚠️ 2026-08-03 重写：旧实现用 `sys.stdout.reconfigure(encoding="utf-8")`，
但 pytest 9.x 的 capture 用 tmpfile 包装 sys.stdout；reconfigure 会让 tmpfile
失效，pytest 退出时抛 `ValueError: I/O operation on closed file`。
新实现：在子进程启动时已通过环境变量 PYTHONIOENCODING=utf-8 设好编码，
pytest capture tmpfile 不需要被替换。
"""
import os
import sys
import tempfile

import pytest


# 在 conftest 加载时立刻生效,优先于任何测试文件 import
# 但不动 sys.stdout 对象本身 —— 避免破坏 pytest capture 的 tmpfile。
if sys.platform == "win32":
    # 子进程用 subprocess 启动时已被 PYTHONIOENCODING=utf-8 覆盖（见 _baseline.md）。
    # 这里只做"保险":如果当前 stdout 编码还不是 utf-8，**只改属性**，不调 reconfigure()。
    if hasattr(sys.stdout, "encoding") and sys.stdout.encoding and not sys.stdout.encoding.lower().startswith("utf"):
        try:
            sys.stdout.encoding = "utf-8"  # type: ignore[attr-defined]
        except Exception:
            pass
    if hasattr(sys.stderr, "encoding") and sys.stderr.encoding and not sys.stderr.encoding.lower().startswith("utf"):
        try:
            sys.stderr.encoding = "utf-8"  # type: ignore[attr-defined]
        except Exception:
            pass


@pytest.fixture(autouse=True)
def _isolate_output_root(tmp_path, monkeypatch):
    """强制把每个测试的输出根隔离到临时目录，防止污染用户真实的
    ~/Desktop/boss-hr-output/。

    为什么需要这个：`output_manager.OUTPUT_ROOT` 是模块级常量，在 import
    那一刻就由 BOSS_HR_OUTPUT_DIR 环境变量固化。测试内部再改环境变量对
    已 import 的模块无效 —— 曾因此在用户桌面留下 9 个「测试XxxJob」空壳
    文件夹（2026-07-29）。所以必须直接 patch 模块属性。
    """
    monkeypatch.setenv("BOSS_HR_OUTPUT_DIR", str(tmp_path))

    _shared = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "shared"))
    if _shared not in sys.path:
        sys.path.insert(0, _shared)

    try:
        import output_manager
    except ImportError:
        # shared/ 不可用的测试（如纯算法测试）无需隔离
        yield
        return

    monkeypatch.setattr(output_manager, "OUTPUT_ROOT", str(tmp_path), raising=False)
    yield
