from contextlib import asynccontextmanager
from pathlib import Path

from alembic import command
from alembic.config import Config
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import UPLOADS_DIR
from .routers import budget, budget_template, categories, category_mappings, dashboard, debug, line_items, receipts, transactions

FRONTEND_BUILD = Path(__file__).resolve().parent.parent.parent / "frontend" / "build"
ALEMBIC_INI = Path(__file__).resolve().parent.parent / "alembic.ini"


@asynccontextmanager
async def lifespan(app: FastAPI):
    alembic_cfg = Config(str(ALEMBIC_INI))
    command.upgrade(alembic_cfg, "head")
    yield


app = FastAPI(title="MoneyTree", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/uploads", StaticFiles(directory=str(UPLOADS_DIR)), name="uploads")

app.include_router(transactions.router)
app.include_router(receipts.router)
app.include_router(line_items.router)
app.include_router(categories.router)
app.include_router(dashboard.router)
app.include_router(budget.router)
app.include_router(budget_template.router)
app.include_router(category_mappings.router)
app.include_router(debug.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}


# Serve SvelteKit static build — must be after API routes
if FRONTEND_BUILD.exists():
    # Serve static assets (JS, CSS, images) directly
    app.mount("/_app", StaticFiles(directory=str(FRONTEND_BUILD / "_app")), name="frontend_assets")

    # SPA fallback: serve index.html for all non-API, non-file routes
    @app.get("/{path:path}")
    async def spa_fallback(request: Request, path: str):
        # Try to serve the exact file first (e.g. manifest.json, icons)
        file_path = FRONTEND_BUILD / path
        if file_path.is_file():
            return FileResponse(file_path)
        # Otherwise serve the SPA fallback
        return FileResponse(FRONTEND_BUILD / "index.html")
