import json

from x2doc.cookies import load_cookies


def test_load_json_filters_to_x_auth_cookies(tmp_path) -> None:
    path = tmp_path / "cookies.json"
    path.write_text(
        json.dumps([{"name": "auth_token", "value": "a"}, {"name": "other", "value": "secret"}]),
        encoding="utf-8",
    )

    cookies = load_cookies(path)

    assert [item["name"] for item in cookies] == ["auth_token"]
    assert cookies[0]["domain"] == ".x.com"


def test_load_netscape_supports_ct0(tmp_path) -> None:
    path = tmp_path / "cookies.txt"
    path.write_text(".x.com\tTRUE\t/\tTRUE\t0\tct0\tcsrf\n", encoding="utf-8")

    assert load_cookies(path)[0]["name"] == "ct0"
