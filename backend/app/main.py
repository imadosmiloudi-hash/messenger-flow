from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.api import auth, events, executions, flows, inbox, media, pages, webhook
from app.bootstrap import init_db
from app.config import get_settings

settings = get_settings()
limiter = Limiter(key_func=get_remote_address, default_limits=[])


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

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(pages.router)
app.include_router(inbox.router)
app.include_router(flows.router)
app.include_router(executions.router)
app.include_router(media.router)
app.include_router(webhook.router)
app.include_router(events.router)


@app.get("/health")
def health():
    return {
        "ok": True,
        "webhook_auto_reply": False,
        "meta_api_version": settings.meta_graph_api_version,
    }


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    if settings.app_env == "development":
        return JSONResponse(status_code=500, content={"detail": str(exc)})
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})
