"""业务逻辑层：认养、天气处置、采摘核销、售后、统计。"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from . import db

# ----------------------------- 基础查询 -----------------------------

def list_farmers() -> list[dict]:
    return db.fetchall("SELECT * FROM farmers ORDER BY id")


def get_farmer(farmer_id: int) -> dict | None:
    return db.fetchone("SELECT * FROM farmers WHERE id = ?", [farmer_id])


def list_plots(farmer_id: int | None = None) -> list[dict]:
    sql = """
        SELECT p.*, f.farm_name, f.name AS farmer_name,
               (SELECT COUNT(*) FROM batches b WHERE b.plot_id = p.id) AS batch_count
        FROM plots p JOIN farmers f ON f.id = p.farmer_id
    """
    params: list[Any] = []
    if farmer_id:
        sql += " WHERE p.farmer_id = ?"
        params.append(farmer_id)
    sql += " ORDER BY p.id"
    return db.fetchall(sql, params)


def get_plot(plot_id: int) -> dict | None:
    return db.fetchone(
        """SELECT p.*, f.farm_name, f.name AS farmer_name, f.phone AS farmer_phone, f.region
           FROM plots p JOIN farmers f ON f.id = p.farmer_id WHERE p.id = ?""",
        [plot_id],
    )


def plot_stats(plot_id: int) -> dict:
    """每块地的认养人数 / 采摘进度 / 售后数量。"""
    row = db.fetchone(
        """
        SELECT
          COUNT(DISTINCT a.id)                                             AS adoption_count,
          COUNT(DISTINCT a.customer_phone)                                 AS customer_count,
          COALESCE(SUM(CASE WHEN a.status IN ('scheduled','picked','completed','rescheduled')
                            THEN a.units END), 0)                          AS adopted_units,
          COALESCE(SUM(CASE WHEN a.status IN ('picked','completed') THEN a.units END), 0) AS picked_units,
          COALESCE(SUM(CASE WHEN a.status = 'completed' THEN a.units END), 0)             AS completed_units,
          SUM(CASE WHEN s2.id IS NOT NULL AND s2.status IN ('open','processing') THEN 1 ELSE 0 END) AS open_issues,
          COUNT(s2.id)                                                     AS total_issues
        FROM adoptions a
        JOIN batches b ON b.id = a.batch_id
        LEFT JOIN after_sales s2 ON s2.adoption_id = a.id
        WHERE b.plot_id = ?
        """,
        [plot_id],
    ) or {}
    return row


def list_batches(plot_id: int | None = None, include_closed: bool = True) -> list[dict]:
    sql = """
        SELECT b.*, p.name AS plot_name, p.plot_type, f.farm_name,
               (SELECT COUNT(*) FROM adoptions a WHERE a.batch_id = b.id
                 AND a.status IN ('scheduled','picked','completed','rescheduled')) AS adopted_count,
               (SELECT COUNT(*) FROM weather_events w WHERE w.batch_id = b.id AND w.status='active') AS active_weather
        FROM batches b
        JOIN plots p ON p.id = b.plot_id
        JOIN farmers f ON f.id = p.farmer_id
        WHERE 1=1
    """
    params: list[Any] = []
    if plot_id:
        sql += " AND b.plot_id = ?"
        params.append(plot_id)
    if not include_closed:
        sql += " AND b.status <> 'closed'"
    sql += " ORDER BY b.status, b.season_start, b.id"
    return db.fetchall(sql, params)


def get_batch(batch_id: int) -> dict | None:
    rows = db.fetchall(
        """
        SELECT b.*, p.name AS plot_name, p.plot_type, p.location, p.id AS plot_id,
               f.farm_name, f.name AS farmer_name, f.phone AS farmer_phone
        FROM batches b
        JOIN plots p ON p.id = b.plot_id
        JOIN farmers f ON f.id = p.farmer_id
        WHERE b.id = ?
        """,
        [batch_id],
    )
    return rows[0] if rows else None


def batch_adoptions(batch_id: int) -> list[dict]:
    return db.fetchall(
        """SELECT a.*, (SELECT COUNT(*) FROM after_sales s WHERE s.adoption_id=a.id) AS issue_count
           FROM adoptions a WHERE a.batch_id = ? ORDER BY a.id""",
        [batch_id],
    )


def active_weather(batch_id: int) -> dict | None:
    return db.fetchone(
        "SELECT * FROM weather_events WHERE batch_id = ? AND status='active' ORDER BY id DESC LIMIT 1",
        [batch_id],
    )


# ----------------------------- 批次状态推导 -----------------------------

def recompute_batch_status(batch_id: int) -> str:
    """依据天气事件、档期、剩余量重新推导批次状态。"""
    b = get_batch(batch_id)
    if not b:
        return "closed"
    today = date.today()
    w = active_weather(batch_id)
    if w:
        status = "affected"
    elif b["remaining_units"] <= 0:
        status = "full"
    elif today > b["season_end"]:
        status = "closed"
    else:
        status = "open"
    db.execute("UPDATE batches SET status = ? WHERE id = ?", [status, batch_id])
    return status


# ----------------------------- 农户：发布地块 / 批次 -----------------------------

class BizError(Exception):
    def __init__(self, message: str, code: str = "biz_error"):
        super().__init__(message)
        self.message = message
        self.code = code


def create_farmer(name: str, phone: str, farm_name: str, region: str) -> int:
    with db.transaction() as conn:
        cur = conn.execute(
            "INSERT INTO farmers(name, phone, farm_name, region, created_at) VALUES(?,?,?,?,?) RETURNING id",
            [name.strip(), phone.strip(), farm_name.strip(), region.strip(), db.now_iso()],
        )
        return int(cur.fetchone()[0])


def create_plot(farmer_id: int, plot_type: str, name: str, location: str,
                area_mu: float, capacity: int, description: str = "") -> int:
    if not get_farmer(farmer_id):
        raise BizError("农户不存在")
    with db.transaction() as conn:
        cur = conn.execute(
            """INSERT INTO plots(farmer_id, plot_type, name, location, area_mu, capacity, description, created_at)
               VALUES(?,?,?,?,?,?,?,?) RETURNING id""",
            [farmer_id, plot_type, name.strip(), location.strip(), area_mu, capacity, description.strip(), db.now_iso()],
        )
        return int(cur.fetchone()[0])


def create_batch(plot_id: int, produce_name: str, unit: str, total_units: float,
                 price_per_unit: float, season_start: str, season_end: str) -> int:
    plot = get_plot(plot_id)
    if not plot:
        raise BizError("地块不存在")
    if datetime.strptime(season_end, "%Y-%m-%d").date() < datetime.strptime(season_start, "%Y-%m-%d").date():
        raise BizError("采摘结束日期不能早于开始日期")
    with db.transaction() as conn:
        cur = conn.execute("SELECT nextval('seq_batches')")
        seq = int(cur.fetchone()[0])
        batch_no = f"B{datetime.now().strftime('%Y%m')}-{seq:04d}"
        cur = conn.execute(
            """INSERT INTO batches(id, plot_id, batch_no, produce_name, unit, total_units, remaining_units,
                                   price_per_unit, season_start, season_end, status, created_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,'open',?) RETURNING id""",
            [seq, plot_id, batch_no, produce_name.strip(), unit, total_units, total_units,
             price_per_unit, season_start, season_end, db.now_iso()],
        )
        return int(cur.fetchone()[0])


# ----------------------------- 消费者认养 -----------------------------

def create_adoption(batch_id: int, customer_name: str, customer_phone: str, units: float,
                    pickup_date: str, delivery: str, address: str = "") -> int:
    b = get_batch(batch_id)
    if not b:
        raise BizError("批次不存在")
    if units <= 0:
        raise BizError("认养数量必须大于 0")
    pdate = datetime.strptime(pickup_date, "%Y-%m-%d").date()
    if pdate < b["season_start"] or pdate > b["season_end"]:
        raise BizError(f"采摘时间需在档期 {b['season_start']} ~ {b['season_end']} 内")
    if b["status"] == "affected":
        raise BizError("该批次受天气影响暂停认养，请选择其他批次或等待恢复")
    if b["status"] == "closed":
        raise BizError("该批次已结束")
    if units > b["remaining_units"]:
        raise BizError(f"库存不足：仅剩 {b['remaining_units']:g} {b['unit']}")
    plot = db.fetchone("SELECT capacity FROM plots WHERE id = ?", [b["plot_id"]])
    distinct = db.fetchone(
        "SELECT COUNT(DISTINCT customer_phone) AS c FROM adoptions a WHERE a.batch_id = ? "
        "AND a.status IN ('scheduled','picked','completed','rescheduled')",
        [batch_id],
    )["c"]
    already = db.fetchone(
        "SELECT COUNT(*) AS c FROM adoptions WHERE batch_id=? AND customer_phone=? "
        "AND status IN ('scheduled','picked','completed','rescheduled')",
        [batch_id, customer_phone.strip()],
    )["c"]
    if plot and already == 0 and distinct >= plot["capacity"]:
        raise BizError("该地块认养人数已达上限")
    amount = round(units * b["price_per_unit"], 2)
    with db.transaction() as conn:
        cur = conn.execute(
            """INSERT INTO adoptions(batch_id, customer_name, customer_phone, units, amount,
                                     pickup_date, delivery, address, status, created_at, updated_at)
               VALUES(?,?,?,?,?,?,?,?,'scheduled',?,?) RETURNING id""",
            [batch_id, customer_name.strip(), customer_phone.strip(), units, amount,
             pickup_date, delivery, address.strip(), db.now_iso(), db.now_iso()],
        )
        aid = int(cur.fetchone()[0])
        conn.execute("UPDATE batches SET remaining_units = remaining_units - ? WHERE id = ?", [units, batch_id])
    recompute_batch_status(batch_id)
    return aid


def get_adoption(adoption_id: int) -> dict | None:
    rows = db.fetchall(
        """SELECT a.*, b.produce_name, b.unit, b.season_start, b.season_end, b.plot_id,
                  p.name AS plot_name, p.plot_type, f.farm_name,
                  w.kind AS weather_kind, w.impact AS weather_impact, w.yield_loss_pct,
                  nb.produce_name AS new_produce_name
           FROM adoptions a
           JOIN batches b ON b.id = a.batch_id
           JOIN plots p ON p.id = b.plot_id
           JOIN farmers f ON f.id = p.farmer_id
           LEFT JOIN weather_events w ON w.id = a.weather_id
           LEFT JOIN batches nb ON nb.id = a.new_batch_id
           WHERE a.id = ?""",
        [adoption_id],
    )
    return rows[0] if rows else None


def list_my_adoptions(phone: str) -> list[dict]:
    return db.fetchall(
        """SELECT a.*, b.produce_name, b.unit, p.name AS plot_name, f.farm_name,
                  w.kind AS weather_kind, w.impact AS weather_impact
           FROM adoptions a
           JOIN batches b ON b.id = a.batch_id
           JOIN plots p ON p.id = b.plot_id
           JOIN farmers f ON f.id = p.farmer_id
           LEFT JOIN weather_events w ON w.id = a.weather_id
           WHERE a.customer_phone = ? ORDER BY a.id DESC""",
        [phone.strip()],
    )


# ----------------------------- 天气事件：触发三选一 -----------------------------

def record_weather(batch_id: int, event_date: str, kind: str, impact: str,
                   yield_loss_pct: int, description: str = "") -> int:
    if not get_batch(batch_id):
        raise BizError("批次不存在")
    if not (0 < yield_loss_pct <= 100):
        raise BizError("减产比例需在 1~100 之间")
    with db.transaction() as conn:
        cur = conn.execute(
            """INSERT INTO weather_events(batch_id, event_date, kind, impact, yield_loss_pct,
                                          description, status, created_at)
               VALUES(?,?,?,?,?,?,'active',?) RETURNING id""",
            [batch_id, event_date, kind, impact.strip(), yield_loss_pct, description.strip(), db.now_iso()],
        )
        wid = int(cur.fetchone()[0])
        # 受影响的有效认养订单挂起，等待消费者选择改期/退款/换批次
        conn.execute(
            """UPDATE adoptions SET weather_id = ?, status = 'scheduled', updated_at = ?
               WHERE batch_id = ? AND status = 'scheduled'""",
            [wid, db.now_iso(), batch_id],
        )
    recompute_batch_status(batch_id)
    return wid


def resolve_weather(weather_id: int) -> None:
    w = db.fetchone("SELECT * FROM weather_events WHERE id = ?", [weather_id])
    if not w:
        raise BizError("天气事件不存在")
    with db.transaction() as conn:
        # 先解除订单对天气事件的外键引用，再更新事件状态（DuckDB 即时外键检查）
        conn.execute(
            "UPDATE adoptions SET weather_id = NULL, updated_at = ? WHERE weather_id = ? AND resolution IS NULL",
            [db.now_iso(), weather_id],
        )
        conn.execute("UPDATE weather_events SET status='resolved' WHERE id = ?", [weather_id])
    recompute_batch_status(w["batch_id"])


def resolve_adoption(adoption_id: int, resolution: str,
                     new_pickup_date: str | None = None, new_batch_id: int | None = None) -> None:
    """消费者针对天气影响做出选择：reschedule / refund / transfer。"""
    a = get_adoption(adoption_id)
    if not a:
        raise BizError("认养订单不存在")
    if not a["weather_id"] or a["resolution"]:
        raise BizError("该订单无需进行天气售后选择")
    ts = db.now_iso()
    with db.transaction() as conn:
        if resolution == "reschedule":
            if not new_pickup_date:
                raise BizError("请选择新的采摘日期")
            nd = datetime.strptime(new_pickup_date, "%Y-%m-%d").date()
            if nd < a["season_start"] or nd > a["season_end"]:
                raise BizError("新日期需在当前批次档期内")
            conn.execute(
                """UPDATE adoptions SET resolution='reschedule', new_pickup_date=?,
                   status='rescheduled', updated_at=? WHERE id=?""",
                [new_pickup_date, ts, adoption_id],
            )
        elif resolution == "refund":
            conn.execute(
                "UPDATE batches SET remaining_units = remaining_units + ? WHERE id = ?",
                [a["units"], a["batch_id"]],
            )
            conn.execute(
                """UPDATE adoptions SET resolution='refund', status='refunded', updated_at=? WHERE id=?""",
                [ts, adoption_id],
            )
        elif resolution == "transfer":
            if not new_batch_id or int(new_batch_id) == a["batch_id"]:
                raise BizError("请选择一个不同的新批次")
            nb = get_batch(int(new_batch_id))
            if not nb:
                raise BizError("目标批次不存在")
            if a["units"] > nb["remaining_units"]:
                raise BizError(f"目标批次库存不足：仅剩 {nb['remaining_units']:g} {nb['unit']}")
            if nb["status"] == "affected":
                raise BizError("目标批次同样受天气影响，请改选其他批次")
            # 退回原批次库存、扣减新批次库存；金额多退少补在 amount 上体现差额
            new_amount = round(a["units"] * nb["price_per_unit"], 2)
            conn.execute(
                "UPDATE batches SET remaining_units = remaining_units + ? WHERE id = ?",
                [a["units"], a["batch_id"]],
            )
            conn.execute(
                "UPDATE batches SET remaining_units = remaining_units - ? WHERE id = ?",
                [a["units"], nb["id"]],
            )
            conn.execute(
                """UPDATE adoptions SET resolution='transfer', new_batch_id=?, batch_id=?,
                   amount=?, pickup_date=?, status='transferred', weather_id=NULL, updated_at=?
                   WHERE id=?""",
                [nb["id"], nb["id"], new_amount, str(nb["season_start"]), ts, adoption_id],
            )
        else:
            raise BizError("无效的售后选择")
    for bid in {a["batch_id"], int(new_batch_id) if new_batch_id else a["batch_id"]}:
        recompute_batch_status(bid)


# ----------------------------- 采摘核销 -----------------------------

def mark_picked(adoption_id: int) -> None:
    a = get_adoption(adoption_id)
    if not a:
        raise BizError("认养订单不存在")
    if a["status"] not in ("scheduled", "rescheduled"):
        raise BizError(f"当前状态【{a['status']}】不能登记采摘")
    db.execute("UPDATE adoptions SET status='picked', updated_at=? WHERE id=?", [db.now_iso(), adoption_id])


def mark_completed(adoption_id: int) -> None:
    a = get_adoption(adoption_id)
    if not a:
        raise BizError("认养订单不存在")
    if a["status"] != "picked":
        raise BizError("只有已采摘订单可核销完成")
    db.execute("UPDATE adoptions SET status='completed', updated_at=? WHERE id=?", [db.now_iso(), adoption_id])


# ----------------------------- 售后 -----------------------------

def create_after_sale(adoption_id: int, kind: str, description: str) -> int:
    if not get_adoption(adoption_id):
        raise BizError("认养订单不存在")
    with db.transaction() as conn:
        cur = conn.execute(
            """INSERT INTO after_sales(adoption_id, kind, description, status, created_at, updated_at)
               VALUES(?, ?, ?, 'open', ?, ?) RETURNING id""",
            [adoption_id, kind, description.strip(), db.now_iso(), db.now_iso()],
        )
        return int(cur.fetchone()[0])


def list_after_sales(status: str | None = None) -> list[dict]:
    sql = """
        SELECT s.*, a.customer_name, a.customer_phone, a.units, b.produce_name, b.unit,
               p.name AS plot_name, p.id AS plot_id, f.farm_name
        FROM after_sales s
        JOIN adoptions a ON a.id = s.adoption_id
        JOIN batches b ON b.id = a.batch_id
        JOIN plots p ON p.id = b.plot_id
        JOIN farmers f ON f.id = p.farmer_id
    """
    params: list[Any] = []
    if status:
        sql += " WHERE s.status = ?"
        params.append(status)
    sql += " ORDER BY CASE s.status WHEN 'open' THEN 0 WHEN 'processing' THEN 1 ELSE 2 END, s.id DESC"
    return db.fetchall(sql, params)


def update_after_sale(sale_id: int, status: str, reply: str | None = None) -> None:
    s = db.fetchone("SELECT * FROM after_sales WHERE id = ?", [sale_id])
    if not s:
        raise BizError("售后单不存在")
    if status not in ("open", "processing", "resolved"):
        raise BizError("无效的售后状态")
    db.execute(
        "UPDATE after_sales SET status=?, reply=COALESCE(?, reply), updated_at=? WHERE id=?",
        [status, (reply.strip() if reply else None), db.now_iso(), sale_id],
    )


# ----------------------------- 管理端总览 -----------------------------

def admin_overview() -> dict:
    totals = db.fetchone(
        """SELECT
            (SELECT COUNT(*) FROM farmers)    AS farmers,
            (SELECT COUNT(*) FROM plots)      AS plots,
            (SELECT COUNT(*) FROM batches)    AS batches,
            (SELECT COUNT(*) FROM adoptions WHERE status IN
                ('scheduled','picked','completed','rescheduled')) AS active_adoptions,
            (SELECT COALESCE(SUM(amount),0) FROM adoptions WHERE status NOT IN ('refunded','cancelled'))
                AS gmv,
            (SELECT COUNT(*) FROM weather_events WHERE status='active') AS active_weather,
            (SELECT COUNT(*) FROM after_sales WHERE status IN ('open','processing')) AS open_issues
        """
    )
    plot_rows = db.fetchall(
        """
        SELECT p.id, p.name, p.plot_type, f.farm_name, p.capacity,
               COUNT(DISTINCT a.id)   AS adoption_count,
               COUNT(DISTINCT a.customer_phone) AS customer_count,
               COALESCE(SUM(CASE WHEN a.status IN ('scheduled','picked','completed','rescheduled')
                                 THEN a.units END),0) AS adopted_units,
               COALESCE(SUM(CASE WHEN a.status IN ('picked','completed') THEN a.units END),0) AS picked_units,
               COALESCE(SUM(CASE WHEN a.status='completed' THEN a.units END),0) AS completed_units,
               COALESCE(SUM(CASE WHEN s2.status IN ('open','processing') THEN 1 ELSE 0 END),0) AS open_issues,
               COUNT(s2.id) AS total_issues,
               COUNT(DISTINCT w.id) AS active_weather
        FROM plots p
        JOIN farmers f ON f.id = p.farmer_id
        LEFT JOIN batches b ON b.plot_id = p.id
        LEFT JOIN adoptions a ON a.batch_id = b.id
        LEFT JOIN after_sales s2 ON s2.adoption_id = a.id
        LEFT JOIN weather_events w ON w.batch_id = b.id AND w.status='active'
        GROUP BY p.id, p.name, p.plot_type, f.farm_name, p.capacity
        ORDER BY p.id
        """
    )
    weather_rows = db.fetchall(
        """SELECT w.*, b.produce_name, b.unit, p.name AS plot_name
           FROM weather_events w JOIN batches b ON b.id=w.batch_id
           JOIN plots p ON p.id=b.plot_id WHERE w.status='active' ORDER BY w.id DESC"""
    )
    batch_rows = db.fetchall(
        """SELECT b.id, b.batch_no, b.produce_name, b.status, b.total_units, b.remaining_units,
                  b.season_start, b.season_end, p.name AS plot_name
           FROM batches b JOIN plots p ON p.id=b.plot_id ORDER BY b.id"""
    )
    return {"totals": totals, "plots": plot_rows, "weather": weather_rows, "batches": batch_rows}


def farmer_overview(farmer_id: int) -> dict:
    plots = db.fetchall(
        """
        SELECT p.*,
               COUNT(DISTINCT a.id) AS adoption_count,
               COALESCE(SUM(CASE WHEN a.status IN ('scheduled','picked','completed','rescheduled')
                                 THEN a.units END),0) AS adopted_units,
               COALESCE(SUM(CASE WHEN a.status IN ('picked','completed') THEN a.units END),0) AS picked_units,
               COUNT(DISTINCT w.id) AS active_weather,
               SUM(CASE WHEN s2.status IN ('open','processing') THEN 1 ELSE 0 END) AS open_issues
        FROM plots p
        LEFT JOIN batches b ON b.plot_id = p.id
        LEFT JOIN adoptions a ON a.batch_id = b.id
        LEFT JOIN after_sales s2 ON s2.adoption_id = a.id
        LEFT JOIN weather_events w ON w.batch_id = b.id AND w.status='active'
        WHERE p.farmer_id = ?
        GROUP BY p.id, p.farmer_id, p.plot_type, p.name, p.location, p.area_mu,
                 p.capacity, p.description, p.created_at
        ORDER BY p.id
        """,
        [farmer_id],
    )
    batches = list_batches_for_farmer(farmer_id)
    return {"plots": plots, "batches": batches}


def list_batches_for_farmer(farmer_id: int) -> list[dict]:
    return db.fetchall(
        """
        SELECT b.*, p.name AS plot_name,
               (SELECT COUNT(*) FROM adoptions a WHERE a.batch_id=b.id
                 AND a.status IN ('scheduled','picked','completed','rescheduled')) AS adopted_count,
               (SELECT COUNT(*) FROM weather_events w WHERE w.batch_id=b.id AND w.status='active') AS active_weather
        FROM batches b JOIN plots p ON p.id=b.plot_id
        WHERE p.farmer_id=? ORDER BY b.id DESC
        """,
        [farmer_id],
    )
