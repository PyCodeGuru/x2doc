from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from x2doc.errors import InaccessibleError, NetworkError, RenderError
from x2doc.fetchers.wechat import WeChatStaticFetcher, classify_wechat_html
from x2doc.platforms import resolve_target

FIXTURES = Path(__file__).parent / "fixtures" / "wechat"


@pytest.mark.parametrize("name", ["deleted.html", "violation.html", "invalid.html"])
def test_inaccessible_wechat_pages_are_exit_two(name: str) -> None:
    with pytest.raises(InaccessibleError):
        classify_wechat_html((FIXTURES / name).read_text(encoding="utf-8"))


def test_antibot_page_is_network_error() -> None:
    with pytest.raises(NetworkError, match="稍后重试"):
        classify_wechat_html((FIXTURES / "antibot.html").read_text(encoding="utf-8"))


def test_static_fetcher_requires_js_content() -> None:
    request = httpx.Request("GET", "https://mp.weixin.qq.com/s/token")
    response = httpx.Response(200, request=request, text="<html>empty</html>")

    class Client:
        def get(self, *_args, **_kwargs):
            return response

    fetcher = WeChatStaticFetcher(client=Client(), clock=lambda: datetime(2026, 7, 27, tzinfo=UTC))
    with pytest.raises(RenderError, match="js_content"):
        fetcher.fetch(resolve_target("https://mp.weixin.qq.com/s/token"), "zh")
