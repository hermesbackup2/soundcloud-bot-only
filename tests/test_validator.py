import os, subprocess, tempfile


def _make_silent_mp3(path, duration=1.0):
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono",
                    "-t", str(duration), "-q:a", "9", "-acodec", "libmp3lame", path],
                   capture_output=True, check=True)


def test_validate_valid_mp3():
    from bot import validate_mp3
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
        path = f.name
    try:
        _make_silent_mp3(path)
        assert validate_mp3(path) is True
    finally:
        if os.path.exists(path): os.remove(path)


def test_validate_nonexistent():
    from bot import validate_mp3
    assert validate_mp3("/tmp/nope_xyz.mp3") is False


def test_validate_tiny():
    from bot import validate_mp3
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
        f.write(b"a"); path = f.name
    try:
        assert validate_mp3(path) is False
    finally:
        if os.path.exists(path): os.remove(path)
