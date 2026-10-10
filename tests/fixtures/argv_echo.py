#!/usr/bin/env python3
"""测试 fixture：把收到的 sys.argv 完整输出到 stdout。

用于验证 cli_runner 参数边界（中文 / 空格 / JSON / 括号不被拆分）。
不在正式 TOOLS 白名单里，仅供 tests/test_cli_runner.py 调用。

支持：
  --exit-code <int>         设置退出码
  --emit <str>              stdout 标记
  --emit-stderr <str>       stderr 内容
  --stdout-prefix <str>     stdout 前缀
  --sleep <float>           睡 N 秒（用于测 timeout）
"""
import argparse
import json
import sys
import time


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--exit-code", type=int, default=0)
    ap.add_argument("--emit", default="ok", help="stdout 标记（用于断言）")
    ap.add_argument("--emit-stderr", default="", help="stderr 内容")
    ap.add_argument("--stdout-prefix", default="[argv_echo]", help="stdout 前缀")
    ap.add_argument("--sleep", type=float, default=0.0, help="sleep N seconds")
    args, unknown = ap.parse_known_args()

    if args.sleep > 0:
        time.sleep(args.sleep)

    out = {
        "argv": sys.argv,
        "unknown": unknown,
        "emit": args.emit,
        "cwd": __import__("os").getcwd(),
    }
    print(args.stdout_prefix + " " + json.dumps(out, ensure_ascii=False))
    if args.emit_stderr:
        print(args.emit_stderr, file=sys.stderr)
    return args.exit_code


if __name__ == "__main__":
    sys.exit(main())