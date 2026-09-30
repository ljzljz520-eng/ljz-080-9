"""消费者：认养、我的订单、天气应对方案选择、售后。"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from .. import db
from ..common import flash, render, require_role

router = APIRouter(prefix="/consumer", tags=["consumer"],
                   dependencies=[Depends(require_role("consumer"))])


def _redirect(path: str) -> RedirectResponse:
    return RedirectResponse(path, status_code=302)


@router.get("")
def my_adoptions(request: Request, user=Depends(require_role("consumer"))):
    adoptions = db.query_all("""
        SELECT a.*, b.name AS batch_name, b.weather_status, b.pickup_start, b.pickup_end,
               p.name AS plot_name, p.crop_type, p.crop_name, p.location,
               (SELECT count(*) FROM resolutions r WHERE r.adoption_id = a.id AND r.status='pending') AS pending_count,
               (SELECT min(e.id) FROM resolutions r JOIN weather_events e ON e.id=r.event_id
                 WHERE r.adoption_id=a.id AND r.status='pending') AS pending_event_id
        FROM adoptions a
        JOIN batches b ON b.id = a.batch_id
        JOIN plots p ON p.id = b.plot_id
        WHERE a.consumer_id = ?
        ORDER BY (a.status='booked') DESC, a.created_at DESC
    """, [user["id"]])
    after_sales = db.query_all("""
        SELECT s.*, a.batch_id FROM after_sales s
        JOIN adoptions a ON a.id = s.adoption_id
        WHERE s.consumer_id = ? ORDER BY s.created_at DESC
    """, [user["id"]])
    return render(request, "consumer/adoptions.html",
                  {"adoptions": adoptions, "after_sales": after_sales})


@router.post("/adoptions")
def create_adoption(request: Request,
                    batch_id: int = Form(...),
                    slots: int = Form(1),
                    scheduled_date: str = Form(...),
                    delivery_mode: str = Form(...),
                    delivery_address: str = Form(""),
                    contact_name: str = Form(...),
                    contact_phone: str = Form(...),
                    user=Depends(require_role("consumer"))):
    resp = _redirect(f"/batches/{batch_id}")
    batch = db.query_one("SELECT * FROM batches WHERE id = ?", [batch_id])
    if not batch or batch["status"] == "closed":
        flash(request, "该批次已结束，无法认养", "error")
        return resp
    if delivery_mode not in ("self_pickup", "platform_delivery", "farm_ship"):
        flash(request, "请选择有效的配送方式", "error")
        return resp
    allowed = (batch["delivery_options"] or "").split(",")
    if delivery_mode not in allowed:
        flash(request, "该批次不支持所选配送方式", "error")
        return resp
    try:
        sched = date.fromisoformat(scheduled_date)
    except ValueError:
        flash(request, "请选择有效的采摘日期", "error")
        return resp
    if sched < batch["pickup_start"] or sched > batch["pickup_end"]:
        flash(request, "采摘时间不在批次开放区间内", "error")
        return resp
    if slots < 1 or slots > 20:
        flash(request, "认养份数需在 1-20 之间", "error")
        return resp
    if delivery_mode != "self_pickup" and not delivery_address.strip():
        flash(request, "选择配送时请填写收货地址", "error")
        return resp

    with db._lock:
        conn = db.get_conn()
        conn.execute("BEGIN TRANSACTION")
        try:
            adopted = conn.execute(
                "SELECT COALESCE(sum(slots),0) FROM adoptions WHERE batch_id=? AND status IN ('booked','picked','rescheduled')",
                [batch_id]).fetchone()[0]
            if adopted + slots > batch["total_slots"]:
                conn.execute("ROLLBACK")
                flash(request, "剩余可认养份数不足", "error")
                return resp
            amount = round(slots * float(batch["unit_price"]), 2)
            aid = conn.execute("""
                INSERT INTO adoptions
                    (batch_id,consumer_id,slots,amount,scheduled_date,delivery_mode,
                     delivery_address,contact_name,contact_phone)
                VALUES (?,?,?,?,?,?,?,?,?) RETURNING id
            """, [batch_id, user["id"], slots, amount, sched, delivery_mode,
                  delivery_address.strip() or None, contact_name.strip(), contact_phone.strip()]
            ).fetchone()[0]
            # 约满自动更新状态
            new_adopted = adopted + slots
            if new_adopted >= batch["total_slots"]:
                conn.execute("UPDATE batches SET status='full' WHERE id=?", [batch_id])
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    resp.headers["location"] = "/consumer"
    flash(request, "认养成功！可在「我的认养」查看订单", "success")
    return resp


@router.get("/adoptions/{adoption_id}/resolution")
def resolution_page(request: Request, adoption_id: int,
                    user=Depends(require_role("consumer"))):
    adoption = _get_owned_adoption(adoption_id, user["id"])
    resolutions = db.query_all("""
        SELECT r.*, e.event_type, e.severity, e.yield_impact_pct, e.description AS event_desc,
               e.event_date, eb.name AS new_batch_name
        FROM resolutions r
        JOIN weather_events e ON e.id = r.event_id
        LEFT JOIN batches eb ON eb.id = r.new_batch_id
        WHERE r.adoption_id = ? AND r.status = 'pending'
        ORDER BY r.created_at
    """, [adoption_id])
    if not resolutions:
        flash(request, "没有待选择的天气应对方案", "info")
        return _redirect("/consumer")
    event = db.query_one("SELECT * FROM weather_events WHERE id = ?",
                         [resolutions[0]["event_id"]])
    return render(request, "consumer/resolution.html",
                  {"adoption": adoption, "resolutions": resolutions, "event": event})


@router.post("/adoptions/{adoption_id}/resolution")
def resolution_decide(request: Request, adoption_id: int,
                      resolution_id: int = Form(...),
                      user=Depends(require_role("consumer"))):
    adoption = _get_owned_adoption(adoption_id, user["id"])
    r = db.query_one(
        "SELECT * FROM resolutions WHERE id = ? AND adoption_id = ? AND status='pending'",
        [resolution_id, adoption_id])
    if not r:
        flash(request, "方案不存在或已处理", "error")
        return _redirect("/consumer")

    batch = db.query_one("SELECT * FROM batches WHERE id=?", [adoption["batch_id"]])
    if r["option"] == "reschedule":
        new_date = r["new_date"]
        if not new_date or new_date < batch["pickup_start"] or new_date > batch["pickup_end"]:
            flash(request, "改期日期不在有效采摘区间", "error")
            return _redirect(f"/consumer/adoptions/{adoption_id}/resolution")
    elif r["option"] == "swap":
        nb = db.query_one("SELECT * FROM batches WHERE id=?", [r["new_batch_id"]])
        if not nb or nb["status"] == "closed":
            flash(request, "目标批次不可用", "error")
            return _redirect(f"/consumer/adoptions/{adoption_id}/resolution")
        adopted = db.query_one(
            "SELECT COALESCE(sum(slots),0) s FROM adoptions WHERE batch_id=? AND status IN ('booked','picked','rescheduled')",
            [nb["id"]])["s"]
        if adopted + adoption["slots"] > nb["total_slots"]:
            flash(request, "目标批次剩余份数不足", "error")
            return _redirect(f"/consumer/adoptions/{adoption_id}/resolution")

    new_status = {"reschedule": "rescheduled", "refund": "refunded", "swap": "swapped"}[r["option"]]
    with db._lock:
        conn = db.get_conn()
        conn.execute("BEGIN TRANSACTION")
        try:
            conn.execute(
                "UPDATE resolutions SET status='accepted', decided_at=now() WHERE id=?",
                [resolution_id])
            conn.execute(
                "UPDATE resolutions SET status='accepted', decided_at=now() WHERE adoption_id=? AND id<>?",
                [adoption_id, resolution_id])
            if r["option"] == "reschedule":
                conn.execute(
                    "UPDATE adoptions SET status='rescheduled', scheduled_date=? WHERE id=?",
                    [r["new_date"], adoption_id])
            elif r["option"] == "refund":
                conn.execute("UPDATE adoptions SET status='refunded' WHERE id=?", [adoption_id])
                _refresh_batch_slot_status(conn, adoption["batch_id"])
            else:  # swap
                conn.execute("UPDATE adoptions SET status='swapped' WHERE id=?", [adoption_id])
                amount = round(adoption["slots"] * float(
                    db.query_one("SELECT unit_price FROM batches WHERE id=?", [r["new_batch_id"]])["unit_price"]), 2)
                conn.execute("""
                    INSERT INTO adoptions
                        (batch_id,consumer_id,slots,amount,scheduled_date,delivery_mode,
                         delivery_address,contact_name,contact_phone,status)
                    VALUES (?,?,?,?,?,?,?,?,?, 'booked')
                """, [r["new_batch_id"], user["id"], adoption["slots"], amount,
                      r["new_date"] or batch["pickup_start"], adoption["delivery_mode"],
                      adoption["delivery_address"], adoption["contact_name"], adoption["contact_phone"]])
                _refresh_batch_slot_status(conn, r["new_batch_id"])
                _refresh_batch_slot_status(conn, adoption["batch_id"])
            # 若事件下所有认养均已处理，则关闭事件
            conn.execute("""
                UPDATE weather_events SET status='resolved'
                WHERE id = ? AND NOT EXISTS (
                    SELECT 1 FROM resolutions rr
                    JOIN adoptions aa ON aa.id = rr.adoption_id
                    JOIN weather_events ee ON ee.id = rr.event_id
                    WHERE ee.id = weather_events.id AND rr.status='pending'
                      AND aa.status IN ('booked','rescheduled'))
            """, [r["event_id"]])
            conn.execute("""
                UPDATE batches SET weather_status='resolved'
                WHERE id = ? AND NOT EXISTS (
                    SELECT 1 FROM weather_events WHERE batch_id=batches.id AND status='open')
            """, [batch["id"]])
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    flash(request, f"已选择「{ {'reschedule':'改期','refund':'退款','swap':'换批次'}[r['option']] }」方案", "success")
    return _redirect("/consumer")


@router.post("/after-sales")
def create_aftersale(request: Request,
                     adoption_id: int = Form(...),
                     issue_type: str = Form(...),
                     content: str = Form(...),
                     user=Depends(require_role("consumer"))):
    adoption = db.query_one(
        "SELECT * FROM adoptions WHERE id=? AND consumer_id=?",
        [adoption_id, user["id"]])
    resp = _redirect("/consumer")
    if not adoption:
        flash(request, "认养订单不存在", "error")
        return resp
    if issue_type not in ("quality", "delivery", "schedule", "other"):
        flash(request, "请选择售后类型", "error")
        return resp
    if not content.strip():
        flash(request, "请描述遇到的问题", "error")
        return resp
    db.execute(
        "INSERT INTO after_sales (adoption_id,consumer_id,issue_type,content) VALUES (?,?,?,?)",
        [adoption_id, user["id"], issue_type, content.strip()])
    flash(request, "售后申请已提交，请等待平台处理", "success")
    return resp


def _get_owned_adoption(adoption_id: int, consumer_id: int) -> dict:
    adoption = db.query_one(
        "SELECT a.*, b.name AS batch_name, b.pickup_start, b.pickup_end FROM adoptions a JOIN batches b ON b.id=a.batch_id WHERE a.id=? AND a.consumer_id=?",
        [adoption_id, consumer_id])
    if not adoption:
        raise HTTPException(status_code=404, detail="认养订单不存在")
    if adoption["status"] not in ("booked", "rescheduled"):
        raise HTTPException(status_code=400, detail="当前订单状态无需选择天气方案")
    return adoption


def _refresh_batch_slot_status(conn, batch_id: int) -> None:
    adopted = conn.execute(
        "SELECT COALESCE(sum(slots),0) FROM adoptions WHERE batch_id=? AND status IN ('booked','picked','rescheduled')",
        [batch_id]).fetchone()[0]
    total = conn.execute("SELECT total_slots, status FROM batches WHERE id=?", [batch_id]).fetchone()
    if total[1] == "closed":
        return
    conn.execute("UPDATE batches SET status=? WHERE id=?",
                 ["full" if adopted >= total[0] else "open", batch_id])
