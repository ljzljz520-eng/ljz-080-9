"""服务端渲染页面：消费者认养 / 农户工作台 / 管理端总览。"""
from __future__ import annotations

import urllib.parse
from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from .. import labels, services

router = APIRouter()

FARMER_ID = 1  # 演示用默认农户（农户工作台无独立登录体系）


def redirect(url: str, msg: str | None = None, ok: bool = True) -> RedirectResponse:
    if msg:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(
            {"msg": msg, "ok": "1" if ok else "0"})
    return RedirectResponse(url, status_code=303)


def safe(call, fallback_url, *args, **kwargs):
    """执行业务写操作，业务错误时带错误信息重定向回来源页。"""
    try:
        return call(*args, **kwargs), None
    except services.BizError as e:
        return None, redirect(fallback_url, e.message, ok=False)


# ============================== 消费者侧 ==============================

@router.get("/")
def home(request: Request):
    batches = services.list_batches(include_closed=False)
    plots = services.list_plots()
    return request.app.state.tpl.TemplateResponse(
        request, "index.html", {"request": request, "batches": batches, "plots": plots})


@router.get("/batches/{batch_id}")
def batch_detail(request: Request, batch_id: int):
    b = services.get_batch(batch_id)
    if not b:
        return redirect("/", "批次不存在", ok=False)
    adoptions = services.batch_adoptions(batch_id)
    weather = services.active_weather(batch_id)
    alternatives = services.list_batches(include_closed=False)
    alternatives = [x for x in alternatives if x["id"] != batch_id and x["status"] != "affected"]
    return request.app.state.tpl.TemplateResponse(
        request, "batch_detail.html",
        {"request": request, "b": b, "adoptions": adoptions, "weather": weather,
         "alternatives": alternatives},
    )


@router.post("/adoptions")
def adopt(request: Request, batch_id: int = Form(...), customer_name: str = Form(...),
          customer_phone: str = Form(...), units: float = Form(...),
          pickup_date: str = Form(...), delivery: str = Form(...), address: str = Form("")):
    aid, err = safe(services.create_adoption, f"/batches/{batch_id}",
                    batch_id, customer_name, customer_phone, units, pickup_date, delivery, address)
    if err:
        return err
    return redirect(f"/my?phone={urllib.parse.quote(customer_phone.strip())}",
                    f"认养成功！订单号 #{aid}，请凭手机号查询。")


@router.get("/my")
def my(request: Request, phone: str = ""):
    adoptions = services.list_my_adoptions(phone) if phone.strip() else []
    alternatives = services.list_batches(include_closed=False)
    alternatives = [x for x in alternatives if x["status"] != "affected"]
    return request.app.state.tpl.TemplateResponse(
        request, "my.html", {"request": request, "phone": phone, "adoptions": adoptions,
                    "alternatives": alternatives})


@router.post("/adoptions/{adoption_id}/resolve")
def resolve_form(request: Request, adoption_id: int, resolution: str = Form(...),
                 new_pickup_date: str = Form(""), new_batch_id: str = Form("")):
    a = services.get_adoption(adoption_id)
    phone = a["customer_phone"] if a else ""
    fallback = f"/my?phone={urllib.parse.quote(phone)}"
    _, err = safe(
        services.resolve_adoption, fallback, adoption_id, resolution,
        new_pickup_date or None, int(new_batch_id) if new_batch_id else None)
    if err:
        return err
    return redirect(fallback, "已提交您的选择：" + labels.RESOLUTION.get(resolution, resolution))


@router.post("/after-sales")
def create_issue(request: Request, adoption_id: int = Form(...), kind: str = Form(...),
                 description: str = Form(...)):
    a = services.get_adoption(adoption_id)
    phone = a["customer_phone"] if a else ""
    _, err = safe(services.create_after_sale, f"/my?phone={urllib.parse.quote(phone)}",
                  adoption_id, kind, description)
    if err:
        return err
    return redirect(f"/my?phone={urllib.parse.quote(phone)}", "售后申请已提交，平台将尽快处理。")


# ============================== 农户工作台 ==============================

@router.get("/farmer")
def farmer_home(request: Request):
    farmer = services.get_farmer(FARMER_ID)
    data = services.farmer_overview(FARMER_ID)
    return request.app.state.tpl.TemplateResponse(
        request, "farmer_dashboard.html", {"request": request, "farmer": farmer, **data})


@router.post("/farmer/plots")
def farmer_plot(request: Request, plot_type: str = Form(...), name: str = Form(...),
                location: str = Form(...), area_mu: float = Form(...),
                capacity: int = Form(...), description: str = Form("")):
    _, err = safe(services.create_plot, "/farmer",
                  FARMER_ID, plot_type, name, location, area_mu, capacity, description)
    if err:
        return err
    return redirect("/farmer", "地块已发布")


@router.post("/farmer/batches")
def farmer_batch(request: Request, plot_id: int = Form(...), produce_name: str = Form(...),
                 unit: str = Form(...), total_units: float = Form(...),
                 price_per_unit: float = Form(...), season_start: str = Form(...),
                 season_end: str = Form(...)):
    _, err = safe(services.create_batch, "/farmer",
                  plot_id, produce_name, unit, total_units, price_per_unit, season_start, season_end)
    if err:
        return err
    return redirect("/farmer", "认养批次已发布")


@router.post("/farmer/weather")
def farmer_weather(request: Request, batch_id: int = Form(...), event_date: str = Form(...),
                   kind: str = Form(...), impact: str = Form(...), yield_loss_pct: int = Form(...),
                   description: str = Form("")):
    wid, err = safe(services.record_weather, "/farmer",
                    batch_id, event_date, kind, impact, yield_loss_pct, description)
    if err:
        return err
    return redirect("/farmer", f"天气事件已登记（#{wid}），相关订单已进入待选择状态", ok=True)


@router.post("/farmer/weather/{weather_id}/resolve")
def farmer_weather_resolve(request: Request, weather_id: int):
    _, err = safe(services.resolve_weather, "/farmer", weather_id)
    if err:
        return err
    return redirect("/farmer", "天气预警已解除，未选择订单恢复正常预约")


@router.post("/farmer/adoptions/{adoption_id}/pick")
def farmer_pick(request: Request, adoption_id: int, batch_id: int = Form(...)):
    _, err = safe(services.mark_picked, f"/farmer/batches/{batch_id}", adoption_id)
    if err:
        return err
    return redirect(f"/farmer/batches/{batch_id}", "采摘已登记")


@router.post("/farmer/adoptions/{adoption_id}/complete")
def farmer_complete(request: Request, adoption_id: int, batch_id: int = Form(...)):
    _, err = safe(services.mark_completed, f"/farmer/batches/{batch_id}", adoption_id)
    if err:
        return err
    return redirect(f"/farmer/batches/{batch_id}", "订单已核销完成")


@router.get("/farmer/batches/{batch_id}")
def farmer_batch_detail(request: Request, batch_id: int):
    b = services.get_batch(batch_id)
    if not b or services.get_plot(b["plot_id"])["farmer_id"] != FARMER_ID:
        return redirect("/farmer", "无权查看该批次", ok=False)
    adoptions = services.batch_adoptions(batch_id)
    weather = services.active_weather(batch_id)
    picked = sum(a["units"] for a in adoptions if a["status"] in ("picked", "completed"))
    total = sum(a["units"] for a in adoptions
                if a["status"] in ("scheduled", "picked", "completed", "rescheduled"))
    return request.app.state.tpl.TemplateResponse(
        request, "farmer_batch.html",
        {"request": request, "b": b, "adoptions": adoptions, "weather": weather,
         "picked_units": picked, "adopted_total": total},
    )


@router.get("/farmer/plots/{plot_id}")
def farmer_plot_detail(request: Request, plot_id: int):
    plot = services.get_plot(plot_id)
    if not plot or plot["farmer_id"] != FARMER_ID:
        return redirect("/farmer", "无权查看该地块", ok=False)
    stats = services.plot_stats(plot_id)
    batches = services.list_batches(plot_id)
    return request.app.state.tpl.TemplateResponse(
        request, "plot_detail.html", {"request": request, "plot": plot, "stats": stats, "batches": batches})


# ============================== 管理端 ==============================

@router.get("/admin")
def admin_home(request: Request):
    data = services.admin_overview()
    return request.app.state.tpl.TemplateResponse(request, "admin.html", {"request": request, **data})


@router.get("/admin/plots/{plot_id}")
def admin_plot(request: Request, plot_id: int):
    plot = services.get_plot(plot_id)
    if not plot:
        return redirect("/admin", "地块不存在", ok=False)
    stats = services.plot_stats(plot_id)
    batches = services.list_batches(plot_id)
    return request.app.state.tpl.TemplateResponse(
        request, "plot_detail.html", {"request": request, "plot": plot, "stats": stats, "batches": batches,
                             "admin_mode": True})


@router.get("/admin/after-sales")
def admin_after_sales(request: Request, status: str | None = None):
    rows = services.list_after_sales(status)
    return request.app.state.tpl.TemplateResponse(
        request, "after_sales.html", {"request": request, "rows": rows, "filter": status})


@router.post("/admin/after-sales/{sale_id}")
def admin_after_sale_update(request: Request, sale_id: int, status: str = Form(...),
                            reply: str = Form("")):
    _, err = safe(services.update_after_sale, "/admin/after-sales", sale_id, status, reply or None)
    if err:
        return err
    return redirect("/admin/after-sales", "售后单已更新")
