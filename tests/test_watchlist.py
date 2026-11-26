from tracker.watchlist import parse_watchlist


def test_parse_watchlist_skips_comments_blank_and_trailing_text():
    text = "# c\n\n  https://a.com/p/1?utm_source=x#top  M\nhttps://a.com/p/1\n"
    assert parse_watchlist(text) == ["https://a.com/p/1"]


def test_parse_watchlist_strips_trailing_slash_and_keeps_order():
    text = "https://a.com/p/2/\nhttps://a.com/p/1\nhttps://a.com/p/2\n"
    assert parse_watchlist(text) == ["https://a.com/p/2", "https://a.com/p/1"]


def test_spao_urls_differing_only_in_item_no_stay_distinct():
    text = (
        "https://www.spao.com/i/item?itemNo=1&lowerVendNo=2\n"
        "https://www.spao.com/i/item?itemNo=3&lowerVendNo=2\n"
    )
    assert parse_watchlist(text) == [
        "https://www.spao.com/i/item?itemNo=1&lowerVendNo=2",
        "https://www.spao.com/i/item?itemNo=3&lowerVendNo=2",
    ]


def test_tracking_params_removed_and_remaining_query_sorted():
    text = "https://a.com/p/1?b=2&a=1&utm_source=x\nhttps://a.com/p/1?a=1&b=2\n"
    assert parse_watchlist(text) == ["https://a.com/p/1?a=1&b=2"]


def test_scheme_and_host_are_case_insensitive():
    text = "HTTPS://A.com/p/1\nhttps://a.com/p/1\n"
    assert parse_watchlist(text) == ["https://a.com/p/1"]
