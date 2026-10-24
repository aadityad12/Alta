"""FastAPI app + /ws hub (hub lands in #15)."""

from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI

REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(REPO_ROOT / ".env")

app = FastAPI(title="Bench")


@app.get("/health")
def health() -> dict:
    return {"ok": True}
