from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.api import auth, events, executions, flows, inbox, integrations_facebook, media, pages, webhook
from app.bootstrap import init_db
from app.config import get_settings

settings = get_settings()
limiter = Limiter(key_func=get_remote_address, default_limits=[])

STATIC_DIR = Path(__file__).resolve().parent / "static"
ASSETS_DIR = STATIC_DIR / "assets"

# Paths that must never be captured by the SPA fallback
_API_PREFIXES = ("api/", "webhook", "health", "media/", "docs", "openapi", "redoc")


@asynccontextmanager
async def lifespan(app: FastAPI):
    Path(settings.media_upload_dir).mkdir(parents=True, exist_ok=True)
    if settings.database_url.startswith("sqlite"):
        Path("./data").mkdir(parents=True, exist_ok=True)
    init_db()
    yield


app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    lifespan=lifespan,
    description=(
        "Messenger Flow Operator — official Meta Graph API only. "
        "Webhook NEVER auto-replies; only authenticated POST send-flow starts sending."
    ),
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Same-origin static UI is primary; keep CORS for optional Next.js frontend during local dev
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- API routes first (take precedence over static / SPA fallback) ---
app.include_router(auth.router)
app.include_router(pages.router)
app.include_router(inbox.router)
app.include_router(flows.router)
app.include_router(executions.router)
app.include_router(media.router)
app.include_router(webhook.router)
app.include_router(integrations_facebook.router)
app.include_router(events.router)


@app.get("/health")
def health():
    return {
        "ok": True,
        "webhook_auto_reply": False,
        "meta_api_version": settings.meta_graph_api_version,
        "messaging_provider": settings.messaging_provider,
        "composio_configured": bool(settings.composio_api_key),
    }


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    if settings.app_env == "development":
        return JSONResponse(status_code=500, content={"detail": str(exc)})
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


# --- Static operator PWA (no build step) ---
if ASSETS_DIR.is_dir():
    app.mount("/assets", StaticFiles(directory=str(ASSETS_DIR)), name="assets")


@app.get("/manifest.json")
def spa_manifest():
    path = STATIC_DIR / "manifest.json"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="manifest not found")
    return FileResponse(path, media_type="application/manifest+json")


@app.get("/sw.js")
def spa_sw():
    path = STATIC_DIR / "sw.js"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="sw.js not found")
    return FileResponse(path, media_type="application/javascript")


@app.get("/icon-192.png")
def spa_icon_192():
    path = STATIC_DIR / "icon-192.png"
    if not path.is_file():
        raise HTTPException(status_code=404)
    return FileResponse(path, media_type="image/png")


@app.get("/icon-512.png")
def spa_icon_512():
    path = STATIC_DIR / "icon-512.png"
    if not path.is_file():
        raise HTTPException(status_code=404)
    return FileResponse(path, media_type="image/png")


@app.get("/")
def spa_index():
    index = STATIC_DIR / "index.html"
    if not index.is_file():
        return JSONResponse(
            status_code=503,
            content={"detail": "Operator UI not packaged. See backend/app/static/."},
        )
    return FileResponse(index, media_type="text/html")


@app.get("/{full_path:path}")
def spa_fallback(full_path: str):
    """Serve static files or index.html for client-side routes.

    Registered last so /api, /webhook, /health, /media/* keep working.
    """
    lowered = full_path.lstrip("/")
    if lowered.startswith(_API_PREFIXES) or lowered in ("health", "webhook", "docs", "openapi.json", "redoc"):
        raise HTTPException(status_code=404, detail="Not found")

    candidate = (STATIC_DIR / full_path).resolve()
    try:
        candidate.relative_to(STATIC_DIR.resolve())
    except ValueError:
        raise HTTPException(status_code=404, detail="Not found") from None

    if candidate.is_file():
        return FileResponse(candidate)

    index = STATIC_DIR / "index.html"
    if index.is_file():
        return FileResponse(index, media_type="text/html")
    raise HTTPException(status_code=404, detail="Not found")
