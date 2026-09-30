"""农户：地块与批次管理、天气事件上报、采摘登记。"""
from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from .. import db
from ..common import flash, render, require_role

router = APIRouter(prefix="/farmer", tags=["farmer"],
                   dependencies=[Depends(require_role("farmer"))])


def _redirect(path: str) -> RedirectResponse:
    return RedirectResponse(path, status_code=302)


def _owned_plot(plot_id: int, farmer_id: int) -> dict:
    plot = db.query_one("SELECT * FROM plots WHERE id=? AND farmer_id=?",
                        [plot_id, farmer_id])
    if not plot:
        raise HTTPException(status_code=404, detail="地块不存在或不属于当前农户")
    return plot


def _owned_batch(batch_id: int, farmer_id: int) -> dict:
    batch = db.query_one("""
        SELECT b.*, p.name AS plot_name, p.farmer_id FROM batches b
        JOIN plots p ON p.id = b.plot_id WHERE b.id=?
    """, [batch_id])
    if not batch or batch["farmer_id"] != farmer_id:
        raise HTTPException(status_code=404, detail="批次不存在或无权管理")
    return batch


@router.get("")
def dashboard(request: Request, user=Depends(require_role("farmer"))):
    plots = db.query_all("""
        SELECT p.*,
          (SELECT count(*) FROM batches b WHERE b.plot_id=p.id) AS batch_count,
          (SELECT count(*) FROM batches b WHERE b.plot_id=p.id AND b.status='open') AS open_batch_count,
          (SELECT COALESCE(sum(a.slots),0) FROM adoptions a JOIN batches b ON b.id=a.batch_id
            WHERE b.plot_id=p.id AND a.status IN ('booked','picked','rescheduled')) AS adopted_slots,
          (SELECT COALESCE(sum(CASE WHEN a.status='picked' THEN a.slots ELSE 0 END),0)
             FROM adoptions a JOIN batches b ON b.id=a.batch_id WHERE b.plot_id=p.id) AS picked_slots
        FROM plots p WHERE p.farmer_id=? ORDER BY p.created_at DESC
    """, [user["id"]])
    kpi = db.query_one("""
        SELECT count(DISTINCT p.id) AS plot_count,
               count(DISTINCT b.id) AS batch_count,
               COALESCE(sum(CASE WHEN a.status IN ('booked','picked','rescheduled') THEN a.slots ELSE 0 END),0) AS adopted_slots,
               COALESCE(sum(CASE WHEN a.status='picked' THEN a.slots ELSE 0 END),0) AS picked_slots,
               count(DISTINCT CASE WHEN e.status='open' THEN e.id END) AS open_events,
               count(DISTINCT CASE WHEN s.status='open' THEN s.id END) AS open_aftersales
        FROM plots p
        LEFT JOIN batches b ON b.plot_id=p.id
        LEFT JOIN adoptions a ON a.batch_id=b.id
        LEFT JOIN weather_events e ON e.batch_id=b.id
        LEFT JOIN after_sales s ON s.adoption_id=a.id
        WHERE p.farmer_id=?
    """, [user["id"]])
    pending = db.query_all("""
        SELECT a.*, b.name AS batch_name, p.name AS plot_name
        FROM adoptions a JOIN batches b ON b.id=a.batch_id JOIN plots p ON p.id=b.plot_id
        WHERE p.farmer_id=? AND a.status IN ('booked','rescheduled')
        ORDER BY a.scheduled_date LIMIT 8
    """, [user["id"]])
    events = db.query_all("""
        SELECT e.*, b.name AS batch_name FROM weather_events e
        JOIN batches b ON b.id=e.batch_id JOIN plots p ON p.id=b.plot_id
        WHERE p.farmer_id=? ORDER BY (e.status='open') DESC, e.created_at DESC LIMIT 6
    """, [user["id"]])
    return render(request, "farmer/dashboard.html",
                  {"plots": plots, "kpi": kpi, "pending": pending, "events": events})


@router.get("/plots/new")
def plot_new_form(request: Request):
    return render(request, "farmer/plot_form.html", {"plot": None})


@router.post("/plots")
def plot_create(request: Request,
                name: str = Form(...), crop_type: str = Form(...),
                crop_name: str = Form(...), location: str = Form(...),
                area_mu: float = Form(0.0), description: str = Form(""),
                user=Depends(require_role("farmer"))):
    if crop_type not in ("orchard", "tea", "vegetable"):
        flash(request, "请选择正确的地块类型", "error")
        return _redirect("/farmer/plots/new")
    pid = db.execute("""
        INSERT INTO plots (farmer_id,name,crop_type,crop_name,location,area_mu,description)
        VALUES (?,?,?,?,?,?,?)
    """, [user["id"], name.strip(), crop_type, crop_name.strip(), location.strip(),
          area_mu, description.strip()])
    flash(request, "地块已发布", "success")
    return _redirect(f"/farmer/plots/{pid}")


@router.get("/plots/{plot_id}")
def plot_detail(request: Request, plot_id: int,
                user=Depends(require_role("farmer"))):
    plot = _owned_plot(plot_id, user["id"])
    batches = db.query_all("""
        SELECT b.*,
          COALESCE((SELECT sum(slots) FROM adoptions a
                     WHERE a.batch_id=b.id AND a.status IN ('booked','picked','rescheduled')),0) AS adopted_slots,
          COALESCE((SELECT sum(slots) FROM adoptions a WHERE a.batch_id=b.id AND a.status='picked'),0) AS picked_slots
        FROM batches b WHERE b.plot_id=? ORDER BY b.created_at DESC
    """, [plot_id])
    return render(request, "farmer/plot_detail.html", {"plot": plot, "batches": batches})


@router.get("/plots/{plot_id}/batches/new")
def batch_new_form(request: Request, plot_id: int,
                   user=Depends(require_role("farmer"))):
    plot = _owned_plot(plot_id, user["id"])
    return render(request, "farmer/batch_form.html", {"plot": plot, "batch": None})


@router.post("/plots/{plot_id}/batches")
def batch_create(request: Request, plot_id: int,
                 name: str = Form(...), season: str = Form(""),
                 total_slots: int = Form(...), unit_price: float = Form(...),
                 yield_desc: str = Form(""),
                 pickup_start: str = Form(...), pickup_end: str = Form(...),
                 delivery_options: list[str] = Form(default=[]),
                 user=Depends(require_role("farmer"))):
    _owned_plot(plot_id, user["id"])
    resp = _redirect(f"/farmer/plots/{plot_id}/batches/new")
    try:
        s, e = date.fromisoformat(pickup_start), date.fromisoformat(pickup_end)
    except ValueError:
        flash(request, "请选择有效的采摘起止日期", "error")
        return resp
    if e < s:
        flash(request, "结束日期不能早于开始日期", "error")
        return resp
    if total_slots < 1 or unit_price < 0:
        flash(request, "认养份数需大于 0，价格不能为负", "error")
        return resp
    valid = [d for d in delivery_options
             if d in ("self_pickup", "platform_delivery", "farm_ship")]
    if not valid:
        flash(request, "请至少选择一种取货/配送方式", "error")
        return resp
    bid = db.execute("""
        INSERT INTO batches (plot_id,name,season,total_slots,unit_price,yield_desc,
                             pickup_start,pickup_end,delivery_options)
        VALUES (?,?,?,?,?,?,?,?,?)
    """, [plot_id, name.strip(), season.strip(), total_slots, unit_price,
          yield_desc.strip(), s, e, ",".join(valid)])
    flash(request, "认养批次已发布", "success")
    return _redirect(f"/farmer/batches/{bid}")


@router.get("/batches/{batch_id}")
def batch_detail(request: Request, batch_id: int,
                 user=Depends(require_role("farmer"))):
    batch = _owned_batch(batch_id, user["id"])
    rows = db.query_all("""
        SELECT a.*, u.display_name AS consumer_name,
               (SELECT count(*) FROM resolutions r WHERE r.adoption_id=a.id AND r.status='pending') AS pending_count
        FROM adoptions a JOIN users u ON u.id=a.consumer_id
        WHERE a.batch_id=? ORDER BY a.scheduled_date, a.id
    """, [batch_id])
    events = db.query_all("""
        SELECT e.*,
          (SELECT count(DISTINCT r.adoption_id) FROM resolutions r WHERE r.event_id=e.id AND r.status='pending') AS pending_adoptions,
          (SELECT count(DISTINCT r.adoption_id) FROM resolutions r WHERE r.event_id=e.id AND r.status='accepted') AS accepted_adoptions,
          (SELECT count(*) FROM adoptions a WHERE a.batch_id=e.batch_id AND a.status IN ('booked','rescheduled')) AS affected_total
        FROM weather_events e WHERE e.batch_id=? ORDER BY e.created_at DESC
    """, [batch_id])
    records = db.query_all("""
        SELECT pr.*, a.contact_name FROM picking_records pr
        JOIN adoptions a ON a.id=pr.adoption_id
        WHERE a.batch_id=? ORDER BY pr.picked_date DESC, pr.id DESC LIMIT 20
    """, [batch_id])
    adopted = sum(r["slots"] for r in rows if r["status"] in ("booked", "picked", "rescheduled"))
    picked = sum(r["slots"] for r in rows if r["status"] == "picked")
    return render(request, "farmer/batch_detail.html",
                  {"batch": batch, "rows": rows, "events": events,
                   "records": records, "adopted": adopted, "picked": picked})


@router.post("/batches/{batch_id}/close")
def batch_close(request: Request, batch_id: int,
                user=Depends(require_role("farmer"))):
    batch = _owned_batch(batch_id, user["id"])
    db.execute("UPDATE batches SET status='closed' WHERE id=?", [batch_id])
    flash(request, "批次已结束", "success")
    return _redirect(f"/farmer/batches/{batch_id}")


@router.post("/batches/{batch_id}/weather")
def weather_create(request: Request, batch_id: int,
                   event_type: str = Form(...), severity: str = Form(...),
                   yield_impact_pct: int = Form(0),
                   event_date: str = Form(...), description: str = Form(""),
                   user=Depends(require_role("farmer"))):
    batch = _owned_batch(batch_id, user["id"])
    resp = _redirect(f"/farmer/batches/{batch_id}")
    if event_type not in ("frost", "hail", "drought", "flood", "typhoon", "heatwave", "pest", "other") \
            or severity not in ("minor", "moderate", "severe"):
        flash(request, "天气类型或影响程度无效", "error")
        return resp
    try:
        ev_date = date.fromisoformat(event_date)
    except ValueError:
        flash(request, "请选择有效的事件日期", "error")
        return resp
    open_event = db.query_one(
        "SELECT id FROM weather_events WHERE batch_id=? AND status='open'", [batch_id])
    if open_event:
        flash(request, "该批次已有待处理天气事件，处理完后再上报", "error")
        return resp
    if batch["status"] == "closed":
        flash(request, "批次已结束，不能上报天气事件", "error")
        return resp

    with db._lock:
        conn = db.get_conn()
        conn.execute("BEGIN TRANSACTION")
        try:
            eid = conn.execute("""
                INSERT INTO weather_events
                    (batch_id,event_type,severity,yield_impact_pct,event_date,description,created_by)
                VALUES (?,?,?,?,?,?,?) RETURNING id
            """, [batch_id, event_type, severity, max(0, min(100, yield_impact_pct)),
                  ev_date, description.strip(), user["id"]]).fetchone()[0]
            conn.execute("UPDATE batches SET weather_status='affected' WHERE id=?", [batch_id])
            # 为所有待采摘/已改期认养生成三选一方案
            adoptions = conn.execute("""
                SELECT id, amount, scheduled_date FROM adoptions
                WHERE batch_id=? AND status IN ('booked','rescheduled')
            """, [batch_id]).fetchall()
            suggestions = db.query_all(
                "SELECT b.id, b.name, b.pickup_start, b.pickup_end, b.status, b.total_slots FROM batches b JOIN plots p ON p.id=b.plot_id WHERE p.farmer_id=? AND b.id<>? AND b.status<>'closed' ORDER BY b.pickup_start LIMIT 5",
                [user["id"], batch_id])
            # 选一个还有余量的批次作为换批建议
            swap_batch = None
            for sb in suggestions:
                used = conn.execute(
                    "SELECT COALESCE(sum(slots),0) FROM adoptions WHERE batch_id=? AND status IN ('booked','picked','rescheduled')",
                    [sb["id"]]).fetchone()[0]
                if used < sb["total_slots"]:
                    swap_batch = sb
                    break
            for aid, amount, sched in adoptions:
                # 采摘日顺延 7 天，并夹在批次开放区间内
                cand = sched + timedelta(days=7)
                cand = min(max(cand, batch["pickup_start"]), batch["pickup_end"])
                conn.execute("""INSERT INTO resolutions (adoption_id,event_id,option,new_date,note)
                    VALUES (?,?, 'reschedule', ?,?)""",
                             [aid, eid, cand, f"建议改期至 {cand.isoformat()} 采摘。"])
                conn.execute("""INSERT INTO resolutions (adoption_id,event_id,option,refund_amount,note)
                    VALUES (?,?, 'refund', ?,?)""",
                             [aid, eid, float(amount), f"按实付金额退款 {float(amount):.2f} 元。"])
                if swap_batch:
                    conn.execute("""INSERT INTO resolutions (adoption_id,event_id,option,new_batch_id,note)
                        VALUES (?,?, 'swap', ?,?)""",
                                 [aid, eid, swap_batch["id"],
                                  f"可换至「{swap_batch['name']}」批次。"])
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    flash(request, "天气事件已上报，平台已为消费者生成应对方案", "success")
    return resp


@router.post("/picking")
def picking_register(request: Request,
                     adoption_id: int = Form(...),
                     picked_date: str = Form(...),
                     weight_kg: float = Form(0.0),
                     note: str = Form(""),
                     user=Depends(require_role("farmer"))):
    adoption = db.query_one("""
        SELECT a.*, p.farmer_id FROM adoptions a
        JOIN batches b ON b.id=a.batch_id JOIN plots p ON p.id=b.plot_id
        WHERE a.id=?
    """, [adoption_id])
    if not adoption or adoption["farmer_id"] != user["id"]:
        flash(request, "认养记录不存在或无权操作", "error")
        return _redirect("/farmer")
    if adoption["status"] not in ("booked", "rescheduled"):
        flash(request, "该认养已登记采摘或已终止", "error")
        return _redirect(f"/farmer/batches/{adoption['batch_id']}")
    try:
        pdate = date.fromisoformat(picked_date)
    except ValueError:
        flash(request, "请选择有效的采摘日期", "error")
        return _redirect(f"/farmer/batches/{adoption['batch_id']}")
    db.execute("""INSERT INTO picking_records (adoption_id,picked_by,picked_date,weight_kg,note)
        VALUES (?,?,?,?,?)""",
               [adoption_id, user["id"], pdate, weight_kg or None, note.strip() or None])
    db.execute("UPDATE adoptions SET status='picked', picked_at=now() WHERE id=?", [adoption_id])
    flash(request, "采摘已登记", "success")
    return _redirect(f"/farmer/batches/{adoption['batch_id']}")
