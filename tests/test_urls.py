def test_single_url():
    from bot import extract_soundcloud_urls
    urls = extract_soundcloud_urls("https://soundcloud.com/artist/track")
    assert urls == ["https://soundcloud.com/artist/track"]


def test_multiple_urls():
    from bot import extract_soundcloud_urls
    text = "https://soundcloud.com/a/b\nhttps://soundcloud.com/c/d\nhttps://soundcloud.com/e/f"
    assert len(extract_soundcloud_urls(text)) == 3


def test_duplicate_urls():
    from bot import extract_soundcloud_urls
    text = "https://soundcloud.com/a/b\nhttps://soundcloud.com/a/b"
    assert len(extract_soundcloud_urls(text)) == 1


def test_no_urls():
    from bot import extract_soundcloud_urls
    assert extract_soundcloud_urls("just text") == []
    assert extract_soundcloud_urls("https://google.com") == []


def test_url_with_trailing_dot():
    from bot import extract_soundcloud_urls
    urls = extract_soundcloud_urls("Check: https://soundcloud.com/a/b.")
    assert urls == ["https://soundcloud.com/a/b"]


def test_url_with_www():
    from bot import extract_soundcloud_urls
    assert len(extract_soundcloud_urls("https://www.soundcloud.com/a/b")) == 1


def test_url_with_on_prefix():
    from bot import extract_soundcloud_urls
    assert len(extract_soundcloud_urls("https://on.soundcloud.com/abc")) == 1
