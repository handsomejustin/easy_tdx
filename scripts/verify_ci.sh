#!/usr/bin/env bash
# easy-tdx 一键本地门禁（等价 CI 的质量检查，v1.27 新增）。
#
# 用法：bash scripts/verify_ci.sh [--fast]
#   --fast 跳过全量测试（只跑 ruff + mypy + 格式检查）
#
# 可选安装为 git hook（pre-push）：
#   ln -s ../../scripts/verify_ci.sh .git/hooks/pre-push

set -euo pipefail
cd "$(dirname "$0")/.."

PY="${PYTHON:-.venv/Scripts/python.exe}"
if [ ! -f "$PY" ]; then
  PY="${PYTHON:-.venv/bin/python}"
fi
if [ ! -f "$PY" ]; then
  PY="python"
fi

FAST=0
[ "${1:-}" = "--fast" ] && FAST=1

echo "── ruff check ──────────────────────────────────────────"
"$PY" -m ruff check src/ tests/

echo "── ruff format --check ─────────────────────────────────"
"$PY" -m ruff format --check src/ tests/

echo "── mypy --strict ───────────────────────────────────────"
"$PY" -m mypy src/easy_tdx/

if [ "$FAST" = "1" ]; then
  echo "── 跳过测试（--fast）───────────────────────────────────"
  echo "✓ verify_ci (fast) 全部通过"
  exit 0
fi

echo "── pytest（全量单元测试）────────────────────────────────"
"$PY" -m pytest tests/ -q --ignore=tests/integration

echo ""
echo "✓ verify_ci 全部通过"
