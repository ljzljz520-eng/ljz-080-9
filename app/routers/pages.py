"""公开页面：首页、批次与地块浏览。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from .. import db
from ..common import render

router = APIRouter(tags=["public"])

BATCH_CARD_SQL = """
SELECT b.*, p.name AS plot_name, p.crop_type, p.crop_name, p.location,
       u.display_name AS farmer_name,
       COALESCE((SELECT sum(slots) FROM adoptions a
                  WHERE a.batch_id = b.id AND a.status IN ('booked','picked','rescheduled')),0) AS adopted_slots
FROM batches b
JOIN plots p ON p.id = b.plot_id
JOIN users u ON u.id = p.farmer_id
"""


@router.get("/")
def home(request: Request):
    stats = db.query_one("""
        SELECT (SELECT count(*) FROM plots) AS plot_count,
               (SELECT count(*) FROM batches WHERE status <> 'closed') AS active_batches,
               (SELECT count(*) FROM users WHERE role='farmer') AS farmer_count,
               (SELECT count(*) FROM adoptions WHERE status IN ('booked','picked','rescheduled')) AS adoption_count
    """)
    batches = db.query_all(
        BATCH_CARD_SQL + " WHERE b.status <> 'closed' ORDER BY b.created_at DESC LIMIT 6")
    return render(request, "home.html", {"stats": stats, "batches": batches})


@router.get("/batches")
def batch_list(request: Request, crop_type: str = "", weather: str = "", q: str = ""):
    where = ["b.status <> 'closed'"]
    params: list = []
    if crop_type in ("orchard", "tea", "vegetable"):
        where.append("p.crop_type = ?")
        params.append(crop_type)
    if weather == "affected":
        where.append("b.weather_status = 'affected'")
    if q:
        where.append("(b.name LIKE ? OR p.crop_name LIKE ? OR p.location LIKE ?)")
        params += [f"%{q}%", f"%{q}%", f"%{q}%"]
    batches = db.query_all(
        BATCH_CARD_SQL + " WHERE " + " AND ".join(where) +
        " ORDER BY b.weather_status='affected' DESC, b.created_at DESC", params)
    return render(request, "batches/list.html",
                  {"batches": batches, "crop_type": crop_type,
                   "weather": weather, "q": q})


@router.get("/batches/{batch_id}")
def batch_detail(request: Request, batch_id: int):
    batch = db.query_one(
        BATCH_CARD_SQL + " WHERE b.id = ?", [batch_id])
    if not batch:
        raise HTTPException(status_code=404, detail="批次不存在")
    events = db.query_all(
        "SELECT * FROM weather_events WHERE batch_id = ? ORDER BY created_at DESC",
        [batch_id])
    active_event = next((e for e in events if e["status"] == "open"), None)
    return render(request, "batches/detail.html",
                  {"batch": batch, "events": events, "active_event": active_event})


@router.get("/plots")
def plot_list(request: Request, crop_type: str = ""):
    where = ["1=1"]
    params: list = []
    if crop_type in ("orchard", "tea", "vegetable"):
        where.append("p.crop_type = ?")
        params.append(crop_type)
    plots = db.query_all("""
        SELECT p.*, u.display_name AS farmer_name,
               (SELECT count(*) FROM batches b WHERE b.plot_id = p.id AND b.status <> 'closed') AS active_batch_count,
               (SELECT count(*) FROM batches b WHERE b.plot_id = p.id) AS total_batch_count
        FROM plots p JOIN users u ON u.id = p.farmer_id
        WHERE """ + " AND ".join(where) + """
        ORDER BY p.created_at DESC
    """, params)
    return render(request, "plots/list.html", {"plots": plots, "crop_type": crop_type})


@router.get("/plots/{plot_id}")
def plot_detail(request: Request, plot_id: int):
    plot = db.query_one("""
        SELECT p.*, u.display_name AS farmer_name, u.phone AS farmer_phone
        FROM plots p JOIN users u ON u.id = p.farmer_id WHERE p.id = ?
    """, [plot_id])
    if not plot:
        raise HTTPException(status_code=404, detail="地块不存在")
    batches = db.query_all(
        BATCH_CARD_SQL + " WHERE p.id = ? ORDER BY b.created_at DESC", [plot_id])
    return render(request, "plots/detail.html", {"plot": plot, "batches": batches})
