from x2doc.models import Platform
from x2doc.platforms import resolve_target


def test_wechat_token_url_is_normalized_without_tracking() -> None:
    target = resolve_target(
        "https://mp.weixin.qq.com/s/AwOk3di8m6eVeIUjzNftgg?scene=1&from=timeline"
    )

    assert target.platform is Platform.WECHAT
    assert target.route == "article"
    assert target.source_id == "AwOk3di8m6eVeIUjzNftgg"
    assert target.canonical_url == "https://mp.weixin.qq.com/s/AwOk3di8m6eVeIUjzNftgg"
    assert target.fetch_paths == ("static", "playwright")


def test_wechat_query_url_uses_stable_source_id_and_clean_url() -> None:
    target = resolve_target(
        "https://mp.weixin.qq.com/s?__biz=MzA1&mid=123&idx=2&sn=abc&chksm=dead&scene=1"
    )

    assert target.source_id == "123-2-abc"
    assert target.canonical_url == "https://mp.weixin.qq.com/s?__biz=MzA1&mid=123&idx=2&sn=abc"
