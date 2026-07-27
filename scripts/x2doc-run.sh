#!/usr/bin/env bash
# 交互式运行 x2doc：准备 venv、检查代理，然后生成 Markdown 和 PDF。

set -u

PROJECT_ROOT="/Users/paipai_tm/Work/tools/x2doc"
VENV_PYTHON="$PROJECT_ROOT/.venv/bin/python"
VENV_X2DOC="$PROJECT_ROOT/.venv/bin/x2doc"

cd "$PROJECT_ROOT" || exit 1

if ! python3 -c 'import sys; raise SystemExit(sys.version_info < (3, 11))' 2>/dev/null; then
  echo "错误：需要 Python 3.11 或更高版本。"
  echo "修复：brew install python@3.12"
  exit 4
fi

if [ ! -x "$VENV_PYTHON" ]; then
  echo "正在创建 .venv……"
  python3 -m venv "$PROJECT_ROOT/.venv" || exit 4
fi

if ! "$VENV_PYTHON" -c 'import x2doc' 2>/dev/null; then
  echo "正在安装 x2doc……"
  "$VENV_PYTHON" -m pip install -e . || exit 4
fi

if ! "$VENV_PYTHON" -c 'from pathlib import Path; from playwright.sync_api import sync_playwright; p=sync_playwright().start(); ok=Path(p.chromium.executable_path).is_file(); p.stop(); raise SystemExit(not ok)' 2>/dev/null; then
  echo "正在安装 Playwright Chromium……"
  "$VENV_PYTHON" -m playwright install chromium || exit 4
fi

if [ -z "${X2DOC_PROXY:-}" ] && [ -z "${HTTPS_PROXY:-}" ] && [ -z "${ALL_PROXY:-}" ]; then
  if nc -z 127.0.0.1 7892 >/dev/null 2>&1; then
    export X2DOC_PROXY="http://127.0.0.1:7892"
    echo "已检测到本机代理：http://127.0.0.1:7892"
  else
    printf "未检测到代理。请输入代理地址，直接回车表示直连："
    read -r entered_proxy
    if [ -n "$entered_proxy" ]; then
      export X2DOC_PROXY="$entered_proxy"
    fi
  fi
fi

echo "正在检查环境……"
"$VENV_X2DOC" doctor || exit 4

printf "请粘贴 X 或微信公众号文章链接："
read -r x_url
if [ -z "$x_url" ]; then
  echo "错误：没有输入链接。"
  exit 1
fi

"$VENV_X2DOC" "$x_url" \
  --format md,pdf \
  --images local \
  --overwrite
