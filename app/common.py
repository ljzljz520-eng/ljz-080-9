"""模板、消息闪现与登录态公共工具。"""
from __future__ import annotations

from pathlib import Path

from fastapi import Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from itsdangerous import BadSignature, URLSafeTimedSerializer

from . import db, labels
from .labels import (
    AFTERSALE_STATUS, AFTERSALE_TYPES, BATCH_STATUS, BATCH_WEATHER_STATUS,
    CROP_ICONS, CROP_TYPES, DELIVERY_MODES, EVENT_STATUS, EVENT_TYPES,
    RESOLUTION_TYPES, SEVERITY,
)

BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = BASE_DIR / "app" / "templates"

SESSION_COOKIE = "farm_session"
FLASH_COOKIE = "farm_flash"
MAX_AGE = 7 * 24 * 3600


def _secret() -> str:
    key_file = BASE_DIR / "data" / ".secret_key"
    if key_file.exists():
        return key_file.read_text().strip()
    import secrets
    key = secrets.token_hex(32)
    key_file.parent.mkdir(parents=True, exist_ok=True)
    key_file.write_text(key)
    return key


serializer = URLSafeTimedSerializer(_secret(), salt="farm-session")

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.globals.update(
    CROP_TYPES=CROP_TYPES, CROP_ICONS=CROP_ICONS, BATCH_STATUS=BATCH_STATUS,
    BATCH_WEATHER_STATUS=BATCH_WEATHER_STATUS, ADOPTION_STATUS=labels.ADOPTION_STATUS,
    DELIVERY_MODES=DELIVERY_MODES, EVENT_TYPES=EVENT_TYPES, SEVERITY=SEVERITY,
    EVENT_STATUS=EVENT_STATUS, RESOLUTION_TYPES=RESOLUTION_TYPES,
    RESOLUTION_STATUS=labels.RESOLUTION_STATUS,
    AFTERSALE_STATUS=AFTERSALE_STATUS, AFTERSALE_TYPES=AFTERSALE_TYPES,
    BADGE_CLASS=labels.BADGE_CLASS,
)
templates.env.filters["money"] = lambda v: f"¥{float(v or 0):,.2f}"
templates.env.filters["date"] = lambda v: v.strftime("%Y-%m-%d") if v else "—"
templates.env.filters["datetime"] = lambda v: v.strftime("%Y-%m-%d %H:%M") if v else "—"


def render(request: Request, template: str, context: dict | None = None):
    ctx = {"request": request, "current_user": getattr(request.state, "user", None)}
    ctx.update(context or {})
    return templates.TemplateResponse(request, template, ctx)


def load_session(request: Request) -> dict:
    raw = request.cookies.get(SESSION_COOKIE)
    if not raw:
        return {}
    try:
        return serializer.loads(raw, max_age=MAX_AGE) or {}
    except BadSignature:
        return {}


def set_session(response: RedirectResponse, data: dict) -> None:
    response.set_cookie(SESSION_COOKIE, serializer.dumps(data),
                        max_age=MAX_AGE, httponly=True, samesite="lax")


def clear_session(response: RedirectResponse) -> None:
    response.delete_cookie(SESSION_COOKIE)


def flash(request: Request, message: str, category: str = "info") -> None:
    request.state.flash = {"message": message, "category": category}


def attach_flash(response, request: Request):
    f = getattr(request.state, "flash", None)
    if f:
        response.set_cookie(FLASH_COOKIE, serializer.dumps(f),
                            max_age=30, httponly=True, samesite="lax")
    else:
        response.delete_cookie(FLASH_COOKIE)
    return response


def get_current_user(request: Request):
    if hasattr(request.state, "user"):
        return request.state.user
    sess = load_session(request)
    uid = sess.get("uid")
    user = db.query_one("SELECT * FROM users WHERE id = ?", [uid]) if uid else None
    request.state.user = user
    return user


def require_user(request: Request):
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=302, headers={"location": "/auth/login?next=" + request.url.path})
    return user


def require_role(*roles: str):
    def _dep(request: Request, user=Depends(require_user)):
        if user["role"] not in roles:
            raise HTTPException(status_code=403, detail="无权访问该页面")
        return user
    return _dep


def consume_flash(request: Request) -> dict | None:
    """读取 flash cookie（模板渲染阶段调用）。"""
    raw = request.cookies.get(FLASH_COOKIE)
    if not raw:
        return None
    try:
        return serializer.loads(raw, max_age=30)
    except BadSignature:
        return None
