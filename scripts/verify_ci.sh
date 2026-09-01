#!/usr/bin/env bash
# easy-tdx 一键本地门禁（等价 CI 的质量检查，v1.27 新增；v1.28 补前端 E2E）。
#
# 用法：bash scripts/verify_ci.sh [--fast] [--no-frontend]
#   --fast        跳过全量测试与前端（只跑 ruff + mypy + 格式检查）
#   --no-frontend 跳过前端 typecheck+build+E2E（只跑 Python 侧）
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
NO_FRONTEND=0
for arg in "$@"; do
  case "$arg" in
    --fast) FAST=1 ;;
    --no-frontend) NO_FRONTEND=1 ;;
  esac
done

echo "── ruff check ──────────────────────────────────────────"
"$PY" -m ruff check src/ tests/

echo "── ruff format --check ─────────────────────────────────"
"$PY" -m ruff format --check src/ tests/

echo "── mypy --strict ───────────────────────────────────────"
"$PY" -m mypy src/easy_tdx/

if [ "$FAST" = "1" ]; then
  echo "── 跳过测试与前端（--fast）─────────────────────────────"
  echo "✓ verify_ci (fast) 全部通过"
  exit 0
fi

echo "── pytest（全量单元测试）────────────────────────────────"
"$PY" -m pytest tests/ -q --ignore=tests/integration

if [ "$NO_FRONTEND" = "0" ] && [ -d web-ui/node_modules ]; then
  echo "── 前端 typecheck + build ──────────────────────────────"
  (cd web-ui && npm run build)

  echo "── Playwright E2E（mock 模式，无需真实行情）────────────"
  (cd web-ui && npm run test:e2e)
else
  echo "── 跳过前端（--no-frontend 或 web-ui/node_modules 缺失）─"
fi

echo ""
echo "✓ verify_ci 全部通过"
