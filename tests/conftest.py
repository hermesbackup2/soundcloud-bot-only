import os, sys, tempfile
os.environ["BOT_TOKEN"] = "123456:TEST_TOKEN_FOR_PYTEST"
_tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp_db.close()
os.environ["DOWNLOAD_HISTORY_DB"] = _tmp_db.name
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
