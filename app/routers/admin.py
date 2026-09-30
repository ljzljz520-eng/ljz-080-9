"""管理端：经营总览、地块认养与采摘进度、售后处理、天气事件监管。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse

from .. import db
from ..common import flash, render, require_role

router = APIRouter(prefix="/admin", tags=["admin"],
                   dependencies=[Depends(require_role("admin"))])


def _redirect(path: str) -> RedirectResponse:
    return RedirectResponse(path, status_code=302)


@router.get("")
def dashboard(request: Request):
    kpi = db.query_one("""
        SELECT
          (SELECT count(*) FROM users WHERE role='farmer') AS farmer_count,
          (SELECT count(*) FROM users WHERE role='consumer') AS consumer_count,
          (SELECT count(*) FROM plots) AS plot_count,
          (SELECT count(*) FROM batches) AS batch_count,
          (SELECT count(*) FROM adoptions WHERE status IN ('booked','picked','rescheduled')) AS active_adoptions,
          (SELECT COALESCE(sum(amount),0) FROM adoptions WHERE status IN ('booked','picked','rescheduled')) AS gmv,
          (SELECT count(*) FROM after_sales WHERE status='open') AS open_aftersales,
          (SELECT count(*) FROM weather_events WHERE status='open') AS open_events
    """)
    plots = db.query_all("""
        SELECT * FROM (
        SELECT p.id, p.name, p.crop_type, p.location, u.display_name AS farmer_name,
          (SELECT count(DISTINCT a.consumer_id) FROM adoptions a JOIN batches b ON b.id=a.batch_id
            WHERE b.plot_id=p.id AND a.status IN ('booked','picked','rescheduled')) AS adopter_count,
          (SELECT COALESCE(sum(a.slots),0) FROM adoptions a JOIN batches b ON b.id=a.batch_id
            WHERE b.plot_id=p.id AND a.status IN ('booked','picked','rescheduled')) AS adopted_slots,
          (SELECT COALESCE(sum(CASE WHEN a.status='picked' THEN a.slots ELSE 0 END),0)
             FROM adoptions a JOIN batches b ON b.id=a.batch_id WHERE b.plot_id=p.id) AS picked_slots,
          (SELECT count(*) FROM after_sales s JOIN adoptions a ON a.id=s.adoption_id
             JOIN batches b ON b.id=a.batch_id WHERE b.plot_id=p.id AND s.status='open') AS open_aftersales,
          (SELECT count(*) FROM weather_events e JOIN batches b ON b.id=e.batch_id
             WHERE b.plot_id=p.id AND e.status='open') AS open_events
        FROM plots p JOIN users u ON u.id=p.farmer_id
        ) t
        ORDER BY (open_aftersales + open_events) DESC, id
    """)
    recent_aftersales = db.query_all("""
        SELECT s.*, u.display_name AS consumer_name, b.name AS batch_name, b.id AS batch_id
        FROM after_sales s
        JOIN users u ON u.id=s.consumer_id
        JOIN adoptions a ON a.id=s.adoption_id
        JOIN batches b ON b.id=a.batch_id
        ORDER BY (s.status='open') DESC, s.created_at DESC LIMIT 8
    """)
    return render(request, "admin/dashboard.html",
                  {"kpi": kpi, "plots": plots, "recent_aftersales": recent_aftersales})


@router.get("/plots/{plot_id}")
def plot_detail(request: Request, plot_id: int):
    plot = db.query_one("""
        SELECT p.*, u.display_name AS farmer_name, u.phone AS farmer_phone
        FROM plots p JOIN users u ON u.id=p.farmer_id WHERE p.id=?
    """, [plot_id])
    batches = db.query_all("""
        SELECT b.*,
          COALESCE((SELECT sum(slots) FROM adoptions a
                     WHERE a.batch_id=b.id AND a.status IN ('booked','picked','rescheduled')),0) AS adopted_slots,
          COALESCE((SELECT count(DISTINCT consumer_id) FROM adoptions a
                     WHERE a.batch_id=b.id AND a.status IN ('booked','picked','rescheduled')),0) AS adopter_count,
          COALESCE((SELECT sum(slots) FROM adoptions a WHERE a.batch_id=b.id AND a.status='picked'),0) AS picked_slots,
          (SELECT count(*) FROM weather_events e WHERE e.batch_id=b.id AND e.status='open') AS open_events
        FROM batches b WHERE b.plot_id=? ORDER BY b.created_at DESC
    """, [plot_id])
    after_sales = db.query_all("""
        SELECT s.*, u.display_name AS consumer_name, a.id AS adoption_id
        FROM after_sales s
        JOIN adoptions a ON a.id=s.adoption_id
        JOIN users u ON u.id=s.consumer_id
        JOIN batches b ON b.id=a.batch_id
        WHERE b.plot_id=? ORDER BY (s.status='open') DESC, s.created_at DESC
    """, [plot_id])
    return render(request, "admin/plot_detail.html",
                  {"plot": plot, "batches": batches, "after_sales": after_sales})


@router.get("/after-sales")
def aftersale_list(request: Request, status: str = ""):
    where = ["1=1"]
    params: list = []
    if status in ("open", "replied", "closed"):
        where.append("s.status = ?")
        params.append(status)
    rows = db.query_all("""
        SELECT s.*, u.display_name AS consumer_name, u.phone AS consumer_phone,
               a.scheduled_date, a.delivery_mode, b.name AS batch_name, b.id AS batch_id,
               p.name AS plot_name
        FROM after_sales s
        JOIN users u ON u.id=s.consumer_id
        JOIN adoptions a ON a.id=s.adoption_id
        JOIN batches b ON b.id=a.batch_id
        JOIN plots p ON p.id=b.plot_id
        WHERE """ + " AND ".join(where) + """
        ORDER BY (s.status='open') DESC, s.updated_at DESC NULLS LAST, s.created_at DESC
    """, params)
    return render(request, "admin/after_sales.html", {"rows": rows, "status": status})


@router.post("/after-sales/{sid}/reply")
def aftersale_reply(request: Request, sid: int,
                    reply: str = Form(...), action: str = Form("reply"),
                    user=Depends(require_role("admin"))):
    item = db.query_one("SELECT * FROM after_sales WHERE id=?", [sid])
    if not item:
        flash(request, "售后单不存在", "error")
        return _redirect("/admin/after-sales")
    new_status = "closed" if action == "close" else "replied"
    db.execute("""UPDATE after_sales SET reply=?, status=?, handled_by=?, updated_at=now()
        WHERE id=?""", [reply.strip(), new_status, user["id"], sid])
    flash(request, "售后已处理", "success")
    return _redirect("/admin/after-sales")


@router.get("/weather-events")
def weather_events(request: Request, status: str = ""):
    where = ["1=1"]
    params: list = []
    if status in ("open", "resolved"):
        where.append("e.status=?")
        params.append(status)
    events = db.query_all("""
        SELECT e.*, b.name AS batch_name, b.id AS batch_id, p.name AS plot_name,
               u.display_name AS farmer_name,
               (SELECT count(DISTINCT r.adoption_id) FROM resolutions r
                 WHERE r.event_id=e.id AND r.status='pending') AS pending_adoptions,
               (SELECT count(DISTINCT r.adoption_id) FROM resolutions r
                 WHERE r.event_id=e.id AND r.status='accepted') AS accepted_adoptions
        FROM weather_events e
        JOIN batches b ON b.id=e.batch_id
        JOIN plots p ON p.id=b.plot_id
        JOIN users u ON u.id=p.farmer_id
        WHERE """ + " AND ".join(where) + """
        ORDER BY (e.status='open') DESC, e.created_at DESC
    """, params)
    return render(request, "admin/weather_events.html",
                  {"events": events, "status": status})


@router.post("/weather-events/{eid}/resolve")
def weather_resolve(request: Request, eid: int,
                    user=Depends(require_role("admin"))):
    event = db.query_one("SELECT * FROM weather_events WHERE id=?", [eid])
    if not event:
        flash(request, "天气事件不存在", "error")
        return _redirect("/admin/weather-events")
    pending = db.query_one(
        "SELECT count(*) c FROM resolutions WHERE event_id=? AND status='pending'", [eid])["c"]
    if pending:
        flash(request, f"仍有 {pending} 位消费者未选择方案，暂时不能关闭事件", "error")
        return _redirect("/admin/weather-events")
    db.execute("UPDATE weather_events SET status='resolved' WHERE id=?", [eid])
    db.execute("""UPDATE batches SET weather_status='resolved' WHERE id=?
        AND NOT EXISTS (SELECT 1 FROM weather_events WHERE batch_id=batches.id AND status='open')""",
               [event["batch_id"]])
    flash(request, "天气事件已标记为处理完成", "success")
    return _redirect("/admin/weather-events")
