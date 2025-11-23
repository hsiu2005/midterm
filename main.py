from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from deps import session_user
from routes_auth import router as auth_router
from routes_client import router as client_router
from routes_contractor import router as contractor_router
from routes_job import router as job_router


app = FastAPI()


# ========== 全域防快取 ==========
@app.middleware("http")
async def add_no_cache_header(request: Request, call_next):
    response: Response = await call_next(request)

    if not request.url.path.startswith(("/static", "/uploads", "/favicon.ico")):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


# ========== Session ==========
app.add_middleware(
    SessionMiddleware,
    secret_key="mysecretkey",
    same_site="lax",
    https_only=False,
)


# ========== 首頁導向 ==========
@app.get("/")
async def index(request: Request):
    uid = request.session.get("user_id")
    role = request.session.get("role")
    if not uid:
        return RedirectResponse(url="/loginForm.html", status_code=302)
    return RedirectResponse(url="/clientJobs.html" if role == "client" else "/contractorMyJobs.html", status_code=302)


# ========== 掛載各個 router ==========
app.include_router(auth_router)
app.include_router(client_router)
app.include_router(contractor_router)
app.include_router(job_router)


# ========== 靜態檔案 ==========
uploads_dir = Path("uploads")
uploads_dir.mkdir(exist_ok=True)
app.mount("/uploads", StaticFiles(directory=uploads_dir), name="uploads")

static_dir = Path("www")
static_dir.mkdir(exist_ok=True)
app.mount("/", StaticFiles(directory=str(static_dir)), name="static")


# ========== 關閉連線池 ==========
try:
    from db import close_pool

    @app.on_event("shutdown")
    async def _shutdown():
        await close_pool()
except Exception:
    pass
