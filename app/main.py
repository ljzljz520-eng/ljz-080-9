"""农产品预售采摘认养平台 —— FastAPI 应用入口。"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import labels
from .routers import api, pages
from .seed import seed_if_empty

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="绿野认养 · 农产品预售采摘认养平台", version="1.0.0")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

tpl = Jinja2Templates(directory=str(BASE_DIR / "templates"))
# 中文标签 / 配色注入到所有模板
tpl.env.globals.update(
    L_PLOT=labels.PLOT_TYPES, L_BATCH=labels.BATCH_STATUS, L_ADOPTION=labels.ADOPTION_STATUS,
    L_DELIVERY=labels.DELIVERY, L_WEATHER=labels.WEATHER_KIND, L_WST=labels.WEATHER_STATUS,
    L_KIND=labels.AFTERSALE_KIND, L_AST=labels.AFTERSALE_STATUS, L_RES=labels.RESOLUTION,
    BADGE=labels.BADGE,
)
tpl.env.filters["money"] = lambda v: f"￥{v:,.2f}" if v is not None else "—"
app.state.tpl = tpl

app.include_router(pages.router)
app.include_router(api.router)


@app.on_event("startup")
def _startup() -> None:
    seed_if_empty()


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    # 页面请求回退为可读错误；接口请求返回 JSON
    if request.url.path.startswith("/api"):
        return JSONResponse(status_code=500, content={"ok": False, "message": str(exc)})
    return JSONResponse(status_code=500,
                        content={"detail": f"服务器错误：{exc}"})
