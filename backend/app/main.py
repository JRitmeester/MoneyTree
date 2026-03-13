import os
from contextlib import asynccontextmanager
from pathlib import Path

from alembic import command
from alembic.config import Config
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from .auth import verify_token
from .config import RP_ORIGIN, UPLOADS_DIR
from .routers import (
    auth,
    budget,
    budget_template,
    categories,
    category_mappings,
    dashboard,
    debug,
    line_items,
    receipts,
    transactions,
    uncategorized,
)

FRONTEND_BUILD = Path(__file__).resolve().parent.parent.parent / "frontend" / "build"
ALEMBIC_INI = Path(__file__).resolve().parent.parent / "alembic.ini"


@asynccontextmanager
async def lifespan(app: FastAPI):
    alembic_cfg = Config(str(ALEMBIC_INI))
    command.upgrade(alembic_cfg, "head")
    yield


app = FastAPI(title="MoneyTree", lifespan=lifespan)

# Rate limiter
app.state.limiter = auth.limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[RP_ORIGIN],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    path = request.url.path
    # Allow auth and health endpoints without authentication
    if path.startswith("/api/auth/") or path == "/api/health":
        return await call_next(request)
    # Allow frontend SPA assets without authentication
    if not path.startswith("/api/") and not path.startswith("/uploads/"):
        return await call_next(request)
    # Protect all /api/* and /uploads/* routes
    token = request.cookies.get("auth_token")
    if not token or not verify_token(token):
        return JSONResponse({"detail": "Not authenticated"}, status_code=401)
    return await call_next(request)


app.mount("/uploads", StaticFiles(directory=str(UPLOADS_DIR)), name="uploads")

app.include_router(auth.router)
app.include_router(transactions.router)
app.include_router(receipts.router)
app.include_router(line_items.router)
app.include_router(categories.router)
app.include_router(dashboard.router)
app.include_router(budget.router)
app.include_router(budget_template.router)
app.include_router(category_mappings.router)
app.include_router(uncategorized.router)

if os.getenv("ENABLE_DEBUG_ROUTES", "").lower() == "true":
    app.include_router(debug.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}


# Serve SvelteKit static build — must be after API routes
if FRONTEND_BUILD.exists():
    app.mount("/_app", StaticFiles(directory=str(FRONTEND_BUILD / "_app")), name="frontend_assets")

    @app.get("/{path:path}")
    async def spa_fallback(request: Request, path: str):
        build_root = FRONTEND_BUILD.resolve()
        file_path = (FRONTEND_BUILD / path).resolve()
        if file_path.is_file() and str(file_path).startswith(str(build_root)):
            return FileResponse(file_path)
        return FileResponse(build_root / "index.html")
