"""登录、注册、退出。"""
from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from .. import db
from ..common import clear_session, flash, render, set_session
from ..security import hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])

HOME_BY_ROLE = {"admin": "/admin", "farmer": "/farmer", "consumer": "/consumer"}


@router.get("/login")
def login_page(request: Request, next: str = ""):
    return render(request, "auth/login.html", {"next_url": next})


@router.post("/login")
def login_submit(request: Request,
                 username: str = Form(...),
                 password: str = Form(...),
                 next: str = Form("")):
    user = db.query_one("SELECT * FROM users WHERE username = ?", [username.strip()])
    resp = RedirectResponse("/auth/login", status_code=302)
    if not user or not verify_password(password, user["password_hash"]):
        flash(request, "用户名或密码错误", "error")
        return attach(resp, request)
    set_session(resp, {"uid": user["id"]})
    target = next if next.startswith("/") else HOME_BY_ROLE.get(user["role"], "/")
    resp.headers["location"] = target
    flash(request, f"欢迎回来，{user['display_name']}", "success")
    return attach(resp, request)


@router.get("/register")
def register_page(request: Request):
    return render(request, "auth/register.html", {})


@router.post("/register")
def register_submit(request: Request,
                    username: str = Form(...),
                    password: str = Form(...),
                    display_name: str = Form(...),
                    phone: str = Form(""),
                    address: str = Form(""),
                    role: str = Form("consumer")):
    username = username.strip()
    resp = RedirectResponse("/auth/register", status_code=302)
    if role not in ("consumer", "farmer"):
        role = "consumer"
    if len(username) < 3 or len(password) < 6:
        flash(request, "用户名至少 3 位，密码至少 6 位", "error")
        return attach(resp, request)
    exists = db.query_one("SELECT id FROM users WHERE username = ?", [username])
    if exists:
        flash(request, "该用户名已被注册", "error")
        return attach(resp, request)
    uid = db.execute(
        "INSERT INTO users (username,password_hash,display_name,role,phone,address) VALUES (?,?,?,?,?,?)",
        [username, hash_password(password), display_name.strip() or username, role, phone, address])
    resp.headers["location"] = HOME_BY_ROLE.get(role, "/")
    set_session(resp, {"uid": uid})
    flash(request, "注册成功，欢迎加入绿野认养！", "success")
    return attach(resp, request)


@router.get("/logout")
def logout(request: Request):
    resp = RedirectResponse("/", status_code=302)
    clear_session(resp)
    flash(request, "您已退出登录", "info")
    return attach(resp, request)


def attach(resp: RedirectResponse, request: Request) -> RedirectResponse:
    """把 flash 消息写到 cookie。"""
    f = getattr(request.state, "flash", None)
    if f:
        from ..common import serializer, FLASH_COOKIE
        resp.set_cookie(FLASH_COOKIE, serializer.dumps(f), max_age=30,
                        httponly=True, samesite="lax")
    return resp
