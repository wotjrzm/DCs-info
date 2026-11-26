from tracker.watchlist import parse_watchlist


def test_parse_watchlist_skips_comments_blank_and_trailing_text():
    text = "# c\n\n  https://a.com/p/1?utm_source=x#top  M\nhttps://a.com/p/1\n"
    assert parse_watchlist(text) == ["https://a.com/p/1"]


def test_parse_watchlist_strips_trailing_slash_and_keeps_order():
    text = "https://a.com/p/2/\nhttps://a.com/p/1\nhttps://a.com/p/2\n"
    assert parse_watchlist(text) == ["https://a.com/p/2", "https://a.com/p/1"]
