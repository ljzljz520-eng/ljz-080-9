"""JSON API：供前后端分离调用或脚本集成，与页面路由共用 services 层。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .. import labels, services
from ..models import (AdoptionIn, AfterSaleIn, AfterSaleUpdate, BatchIn, PlotIn,
                      ResolveIn, WeatherIn)

router = APIRouter(prefix="/api", tags=["api"])


def _ok(data=None, **extra):
    payload = {"ok": True}
    if data is not None:
        payload["data"] = data
    payload.update(extra)
    return payload


def _biz(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except services.BizError as e:
        raise HTTPException(status_code=400, detail={"code": e.code, "message": e.message})


# ---------- 资源查询 ----------

@router.get("/farmers")
def get_farmers():
    return _ok(services.list_farmers())


@router.get("/plots")
def get_plots(farmer_id: int | None = None):
    return _ok(services.list_plots(farmer_id))


@router.get("/plots/{plot_id}")
def get_plot_detail(plot_id: int):
    plot = services.get_plot(plot_id)
    if not plot:
        raise HTTPException(404, "地块不存在")
    return _ok({"plot": plot, "stats": services.plot_stats(plot_id),
                "batches": services.list_batches(plot_id)})


@router.get("/batches")
def get_batches(plot_id: int | None = None, include_closed: bool = True):
    return _ok(services.list_batches(plot_id, include_closed))


@router.get("/batches/{batch_id}")
def get_batch_detail(batch_id: int):
    b = services.get_batch(batch_id)
    if not b:
        raise HTTPException(404, "批次不存在")
    return _ok({"batch": b, "adoptions": services.batch_adoptions(batch_id),
                "weather": services.active_weather(batch_id)})


@router.get("/adoptions/{adoption_id}")
def get_adoption(adoption_id: int):
    a = services.get_adoption(adoption_id)
    if not a:
        raise HTTPException(404, "认养订单不存在")
    return _ok(a)


@router.get("/my-adoptions")
def my_adoptions(phone: str):
    return _ok(services.list_my_adoptions(phone))


# ---------- 农户发布 ----------

@router.post("/plots")
def post_plot(payload: PlotIn):
    pid = _biz(services.create_plot, **payload.model_dump())
    return _ok({"id": pid})


@router.post("/batches")
def post_batch(payload: BatchIn):
    data = payload.model_dump()
    data["season_start"] = data["season_start"].isoformat()
    data["season_end"] = data["season_end"].isoformat()
    bid = _biz(services.create_batch, **data)
    return _ok({"id": bid})


# ---------- 消费者认养 ----------

@router.post("/adoptions")
def post_adoption(payload: AdoptionIn):
    data = payload.model_dump()
    data["pickup_date"] = data["pickup_date"].isoformat()
    aid = _biz(services.create_adoption, **data)
    return _ok({"id": aid})


@router.post("/adoptions/{adoption_id}/resolve")
def post_resolve(adoption_id: int, payload: ResolveIn):
    data = payload.model_dump(exclude_none=True)
    if data.get("new_pickup_date"):
        data["new_pickup_date"] = data["new_pickup_date"].isoformat()
    _biz(services.resolve_adoption, adoption_id, **data)
    return _ok()


@router.post("/adoptions/{adoption_id}/pick")
def post_pick(adoption_id: int):
    _biz(services.mark_picked, adoption_id)
    return _ok()


@router.post("/adoptions/{adoption_id}/complete")
def post_complete(adoption_id: int):
    _biz(services.mark_completed, adoption_id)
    return _ok()


# ---------- 天气 ----------

@router.post("/weather")
def post_weather(payload: WeatherIn):
    data = payload.model_dump()
    data["event_date"] = data["event_date"].isoformat()
    wid = _biz(services.record_weather, **data)
    return _ok({"id": wid})


@router.post("/weather/{weather_id}/resolve")
def post_weather_resolve(weather_id: int):
    _biz(services.resolve_weather, weather_id)
    return _ok()


# ---------- 售后 ----------

@router.get("/after-sales")
def get_after_sales(status: str | None = None):
    return _ok(services.list_after_sales(status))


@router.post("/after-sales")
def post_after_sale(payload: AfterSaleIn):
    sid = _biz(services.create_after_sale, **payload.model_dump())
    return _ok({"id": sid})


@router.patch("/after-sales/{sale_id}")
def patch_after_sale(sale_id: int, payload: AfterSaleUpdate):
    _biz(services.update_after_sale, sale_id, **payload.model_dump(exclude_none=True))
    return _ok()


# ---------- 管理端 ----------

@router.get("/admin/overview")
def get_admin_overview():
    return _ok(services.admin_overview())
