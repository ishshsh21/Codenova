"""Test package.

The environment is set here, before any test module imports the app, so the app
always binds to a throwaway database. DbTestCase additionally refuses to run
against anything else, because it drops and recreates every table.
"""
import atexit
import os
import shutil
import tempfile

# A file (not :memory:) so the threads FastAPI's TestClient uses share one database.
TEST_DB_DIR = tempfile.mkdtemp(prefix="workday-tests-")
atexit.register(shutil.rmtree, TEST_DB_DIR, ignore_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB_DIR}/test.db"
os.environ["APP_SECRET_KEY"] = "test-secret"
os.environ["GOOGLE_CLIENT_ID"] = "test-client"
os.environ["GOOGLE_CLIENT_SECRET"] = "test-client-secret"
os.environ["GEMINI_API_KEY"] = ""
