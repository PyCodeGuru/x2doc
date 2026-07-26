"""Load only the X authentication cookies accepted by x2doc."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from x2doc.errors import ParameterError

_ALLOWED = {"auth_token", "ct0"}


def load_cookies(path: str | Path) -> list[dict[str, Any]]:
    source = Path(path)
    try:
        text = source.read_text(encoding="utf-8")
    except OSError as exc:
        raise ParameterError(f"无法读取 cookies 文件: {source}") from exc
    cookies = _load_json(text) if text.lstrip().startswith(("[", "{")) else _load_netscape(text)
    selected = [cookie for cookie in cookies if cookie.get("name") in _ALLOWED]
    if not selected:
        raise ParameterError("cookies 文件中没有 auth_token 或 ct0")
    return selected


def _load_json(text: str) -> list[dict[str, Any]]:
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ParameterError("cookies JSON 格式无效") from exc
    items = value.get("cookies") if isinstance(value, dict) else value
    if not isinstance(items, list):
        raise ParameterError("cookies JSON 顶层必须是数组或 cookies 对象")
    result = []
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            continue
        result.append(
            {
                "name": item["name"],
                "value": str(item.get("value", "")),
                "domain": item.get("domain") or ".x.com",
                "path": item.get("path") or "/",
                "secure": bool(item.get("secure", True)),
            }
        )
    return result


def _load_netscape(text: str) -> list[dict[str, Any]]:
    result = []
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) != 7:
            continue
        domain, _include, path, secure, _expires, name, value = parts
        result.append(
            {
                "name": name,
                "value": value,
                "domain": domain,
                "path": path,
                "secure": secure.upper() == "TRUE",
            }
        )
    return result
