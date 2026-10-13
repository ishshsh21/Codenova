import os
import sys
import tempfile
from pathlib import Path

# Point the app at a throwaway SQLite file before anything imports app.database.
_db = Path(tempfile.mkdtemp()) / "test.db"
os.environ["DATABASE_URL"] = f"sqlite:///{_db}"
os.environ["GEMINI_API_KEY"] = ""
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
