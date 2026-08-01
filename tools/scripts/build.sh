#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$ROOT_DIR"

VARIANT="${1:-Enhanced}"
case "$VARIANT" in
  Enhanced|Standard|Lite) ;;
  *)
    echo "错误: 版本类型无效: $VARIANT" >&2
    exit 1
    ;;
esac

command -v uv >/dev/null 2>&1 || {
  echo "错误: 未找到 uv" >&2
  exit 1
}

uv sync --extra build --frozen
uv run --frozen python tools/build_portable.py \
  --variant "$VARIANT" \
  --target app \
  --output dist
