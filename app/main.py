"""FastAPI 应用入口。"""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import db
from .common import consume_flash, templates
from .routers import admin, auth, consumer, farmer, pages

BASE_DIR = __import__("pathlib").Path(__file__).resolve().parent.parent

app = FastAPI(title="绿野认养 · 农产品预售采摘认养平台")
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

app.include_router(pages.router)
app.include_router(auth.router)
app.include_router(consumer.router)
app.include_router(farmer.router)
app.include_router(admin.router)


@app.on_event("startup")
def _startup() -> None:
    db.get_conn()  # 初始化表与种子数据


@app.middleware("http")
async def flash_middleware(request: Request, call_next):
    # 将 cookie 中的 flash 暂存到 request.state，供模板使用
    f = consume_flash(request)
    if f:
        request.state.flash_incoming = f
    response = await call_next(request)
    return response


@app.exception_handler(302)
async def redirect_handler(request: Request, exc):
    return RedirectResponse(url=exc.headers.get("location", "/"), status_code=302)


@app.exception_handler(403)
async def forbidden_handler(request: Request, exc):
    return templates.TemplateResponse(
        request, "error.html",
        {"request": request, "current_user": None,
         "code": 403, "message": "抱歉，您没有权限访问此页面。"},
        status_code=403,
    )


@app.exception_handler(404)
async def notfound_handler(request: Request, exc):
    return templates.TemplateResponse(
        request, "error.html",
        {"request": request, "current_user": None,
         "code": 404, "message": "页面走丢了，回首页看看吧。"},
        status_code=404,
    )
