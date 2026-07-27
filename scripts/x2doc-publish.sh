#!/bin/sh
set -eu

# 固定入口避免手机端 Codex 临时拼接 Git 命令或切错仓库。
PROJECT_ROOT="/Users/paipai_tm/Work/tools/x2doc"
PYTHON="${X2DOC_PUBLISH_PYTHON:-$PROJECT_ROOT/.venv/bin/python}"

if [ "$#" -ne 1 ]; then
  echo '错误：必须提供一个 X 或微信公众号链接。' >&2
  exit 1
fi

if [ ! -x "$PYTHON" ]; then
  echo '错误：x2doc Python 环境不存在。请先按 docs/使用指南.md 完成安装。' >&2
  exit 4
fi

cd "$PROJECT_ROOT"
exec "$PYTHON" "$PROJECT_ROOT/scripts/x2doc_publish.py" "$1"
