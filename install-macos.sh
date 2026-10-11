#!/bin/sh
# 在独立虚拟环境中安装 CLI；安装时不启动浏览器或访问 BOSS。
set -eu

if [ "$(uname -s)" != "Darwin" ]; then
    echo "[install-macos] ERROR: this script requires macOS." >&2
    exit 1
fi

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$ROOT"

if ! command -v python3 >/dev/null 2>&1; then
    echo "[install-macos] ERROR: python3 not found in PATH." >&2
    exit 1
fi

python3 -c 'import sys; sys.exit(sys.version_info < (3, 10))' || {
    echo "[install-macos] ERROR: Python 3.10+ required." >&2
    exit 1
}

python3 -m venv .venv
.venv/bin/python -m pip install -e .

# Some macOS setups mark generated .pth files hidden; Python 3.14 then skips
# them. sitecustomize keeps this editable source tree importable from the venv.
.venv/bin/python - "$ROOT" <<'PY'
from pathlib import Path
import site
import sys

root = Path(sys.argv[1]).resolve()
customize = Path(site.getsitepackages()[0]) / "sitecustomize.py"
customize.write_text(
    f"import sys\nsource = {str(root)!r}\n"
    "if source not in sys.path:\n    sys.path.insert(0, source)\n",
    encoding="utf-8",
)
PY

(cd / && "$ROOT/.venv/bin/boss-hr" --help >/dev/null)

echo "[install-macos] OK. Run: source .venv/bin/activate"
echo "[install-macos] Keep the source directory at: $ROOT"
