import uuid


def _unique_user():
    return abs(hash(uuid.uuid4())) % 1000000


def test_add_and_get_history():
    from services import history
    uid = _unique_user()
    history.add_download(uid, "abc", "Test Track", "Test Artist", "url", 180000)
    rows = history.get_user_history(uid)
    assert len(rows) >= 1
    assert rows[0]["title"] == "Test Track"


def test_stats():
    from services import history
    uid = _unique_user()
    history.add_download(uid, "x", "T1", "A", "u", 0)
    history.add_download(uid, "y", "T2", "A", "u", 0)
    stats = history.get_user_stats(uid)
    assert stats["total"] >= 2


def test_top_artists():
    from services import history
    uid = _unique_user()
    for _ in range(3):
        history.add_download(uid, "z", "T", "Dariush", "u", 0)
    history.add_download(uid, "w", "T", "Ebi", "u", 0)
    stats = history.get_user_stats(uid)
    assert stats["top_artists"][0]["artist"] == "Dariush"


def test_global_top():
    from services import history
    top = history.get_global_top(limit=10)
    assert isinstance(top, list)


def test_empty_history():
    from services import history
    uid = _unique_user()
    rows = history.get_user_history(uid)
    assert rows == []
