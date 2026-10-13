import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.database import Base, engine, migrate_sqlite_schema
from app.routers import auth, gmail, tasks, agenda, fyi, search, assistant

# Never log raw email bodies or OAuth tokens (TRD Section 10/14).
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logging.getLogger("workday_agent").setLevel(logging.INFO)

settings = get_settings()

Base.metadata.create_all(bind=engine)
migrate_sqlite_schema()

app = FastAPI(
    title="Gmail AI Workday Agent",
    version="1.0.0",
    description="Gmail-only AI task intelligence and agenda planning system (read-only, gmail.readonly scope).",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(gmail.router)
app.include_router(tasks.router)
app.include_router(agenda.router)
app.include_router(fyi.router)
app.include_router(search.router)
app.include_router(assistant.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}
