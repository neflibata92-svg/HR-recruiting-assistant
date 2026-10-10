# -*- coding: utf-8 -*-
"""boss_hr 包入口 — 让 `python -m boss_hr` 工作。

行为完全等同于 `python -m boss_hr.cli`；包装一层让标准 Python
"-m 包名" 习惯能直接调到统一 CLI。

不引入新逻辑；不改 main() 签名；只做 sys.exit 转交。
"""
import sys

from boss_hr.cli import main


if __name__ == "__main__":
    sys.exit(main())