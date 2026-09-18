def test_private_error():
    from services.downloader import classify_error
    msg = classify_error(Exception("This video is private"))
    assert "🔒" in msg or "private" in msg.lower()


def test_geo_error():
    from services.downloader import classify_error
    msg = classify_error(Exception("Not available in your country"))
    assert "🌍" in msg or "منطقه" in msg


def test_timeout_error():
    from services.downloader import classify_error
    msg = classify_error(Exception("Connection timed out"))
    assert "⏱️" in msg or "timeout" in msg.lower()


def test_404_error():
    from services.downloader import classify_error
    msg = classify_error(Exception("404 Not Found"))
    assert "❓" in msg or "پیدا نشد" in msg


def test_too_large_error():
    from services.downloader import classify_error
    msg = classify_error(Exception("Request Entity Too Large"))
    assert "📦" in msg or "بزرگ" in msg


def test_unknown_error():
    from services.downloader import classify_error
    msg = classify_error(Exception("something weird"))
    assert msg.startswith("❌") or "خطا" in msg
