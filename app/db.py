"""DuckDB 数据访问层：连接管理、建表、种子数据。"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import duckdb

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "farm.db"

_lock = threading.RLock()
_conn: duckdb.DuckDBPyConnection | None = None


def get_conn() -> duckdb.DuckDBPyConnection:
    global _conn
    if _conn is None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _conn = duckdb.connect(str(DB_PATH))
        init_db(_conn)
    return _conn


def query_all(sql: str, params: list[Any] | tuple = ()) -> list[dict]:
    with _lock:
        cur = get_conn().execute(sql, list(params))
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def query_one(sql: str, params: list[Any] | tuple = ()) -> dict | None:
    with _lock:
        cur = get_conn().execute(sql, list(params))
        cols = [d[0] for d in cur.description]
        row = cur.fetchone()
        return dict(zip(cols, row)) if row else None


def execute(sql: str, params: list[Any] | tuple = ()) -> int:
    """执行写操作并返回最后生成的 id（仅 INSERT 返回新 id，其余返回 -1）。"""
    with _lock:
        conn = get_conn()
        if sql.lstrip().upper().startswith("INSERT"):
            cur = conn.execute(sql.rstrip().rstrip(";") + " RETURNING id", list(params))
            row = cur.fetchone()
            return int(row[0]) if row else -1
        conn.execute(sql, list(params))
        return -1


SCHEMA = """
CREATE SEQUENCE IF NOT EXISTS seq_users;
CREATE SEQUENCE IF NOT EXISTS seq_plots;
CREATE SEQUENCE IF NOT EXISTS seq_batches;
CREATE SEQUENCE IF NOT EXISTS seq_adoptions;
CREATE SEQUENCE IF NOT EXISTS seq_weather_events;
CREATE SEQUENCE IF NOT EXISTS seq_resolutions;
CREATE SEQUENCE IF NOT EXISTS seq_picking_records;
CREATE SEQUENCE IF NOT EXISTS seq_after_sales;

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY DEFAULT nextval('seq_users'),
    username VARCHAR UNIQUE NOT NULL,
    password_hash VARCHAR NOT NULL,
    display_name VARCHAR NOT NULL,
    role VARCHAR NOT NULL CHECK (role IN ('admin','farmer','consumer')),
    phone VARCHAR,
    address VARCHAR,
    created_at TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS plots (
    id INTEGER PRIMARY KEY DEFAULT nextval('seq_plots'),
    farmer_id INTEGER NOT NULL REFERENCES users(id),
    name VARCHAR NOT NULL,
    crop_type VARCHAR NOT NULL CHECK (crop_type IN ('orchard','tea','vegetable')),
    crop_name VARCHAR NOT NULL,
    location VARCHAR NOT NULL,
    area_mu DOUBLE NOT NULL DEFAULT 0,
    description VARCHAR,
    created_at TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS batches (
    id INTEGER PRIMARY KEY DEFAULT nextval('seq_batches'),
    plot_id INTEGER NOT NULL REFERENCES plots(id),
    name VARCHAR NOT NULL,
    season VARCHAR,
    total_slots INTEGER NOT NULL CHECK (total_slots > 0),
    unit_price DOUBLE NOT NULL CHECK (unit_price >= 0),
    yield_desc VARCHAR,
    pickup_start DATE NOT NULL,
    pickup_end DATE NOT NULL,
    delivery_options VARCHAR NOT NULL DEFAULT 'self_pickup',
    status VARCHAR NOT NULL DEFAULT 'open'
        CHECK (status IN ('open','full','closed')),
    weather_status VARCHAR NOT NULL DEFAULT 'normal'
        CHECK (weather_status IN ('normal','affected','resolved')),
    created_at TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS adoptions (
    id INTEGER PRIMARY KEY DEFAULT nextval('seq_adoptions'),
    batch_id INTEGER NOT NULL REFERENCES batches(id),
    consumer_id INTEGER NOT NULL REFERENCES users(id),
    slots INTEGER NOT NULL CHECK (slots > 0),
    amount DOUBLE NOT NULL,
    scheduled_date DATE NOT NULL,
    delivery_mode VARCHAR NOT NULL
        CHECK (delivery_mode IN ('self_pickup','platform_delivery','farm_ship')),
    delivery_address VARCHAR,
    contact_name VARCHAR NOT NULL,
    contact_phone VARCHAR NOT NULL,
    status VARCHAR NOT NULL DEFAULT 'booked'
        CHECK (status IN ('booked','picked','rescheduled','refunded','swapped','cancelled')),
    picked_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS weather_events (
    id INTEGER PRIMARY KEY DEFAULT nextval('seq_weather_events'),
    batch_id INTEGER NOT NULL REFERENCES batches(id),
    event_type VARCHAR NOT NULL
        CHECK (event_type IN ('frost','hail','drought','flood','typhoon','heatwave','pest','other')),
    severity VARCHAR NOT NULL CHECK (severity IN ('minor','moderate','severe')),
    yield_impact_pct INTEGER NOT NULL DEFAULT 0
        CHECK (yield_impact_pct >= 0 AND yield_impact_pct <= 100),
    event_date DATE NOT NULL,
    description VARCHAR,
    status VARCHAR NOT NULL DEFAULT 'open' CHECK (status IN ('open','resolved')),
    created_by INTEGER REFERENCES users(id),
    created_at TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS resolutions (
    id INTEGER PRIMARY KEY DEFAULT nextval('seq_resolutions'),
    adoption_id INTEGER NOT NULL REFERENCES adoptions(id),
    event_id INTEGER NOT NULL REFERENCES weather_events(id),
    option VARCHAR NOT NULL CHECK (option IN ('reschedule','refund','swap')),
    new_date DATE,
    new_batch_id INTEGER REFERENCES batches(id),
    refund_amount DOUBLE,
    note VARCHAR,
    status VARCHAR NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','accepted')),
    decided_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS picking_records (
    id INTEGER PRIMARY KEY DEFAULT nextval('seq_picking_records'),
    adoption_id INTEGER NOT NULL REFERENCES adoptions(id),
    picked_by INTEGER REFERENCES users(id),
    picked_date DATE NOT NULL,
    weight_kg DOUBLE,
    note VARCHAR,
    created_at TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS after_sales (
    id INTEGER PRIMARY KEY DEFAULT nextval('seq_after_sales'),
    adoption_id INTEGER NOT NULL REFERENCES adoptions(id),
    consumer_id INTEGER NOT NULL REFERENCES users(id),
    issue_type VARCHAR NOT NULL
        CHECK (issue_type IN ('quality','delivery','schedule','other')),
    content VARCHAR NOT NULL,
    status VARCHAR NOT NULL DEFAULT 'open'
        CHECK (status IN ('open','replied','closed')),
    reply VARCHAR,
    handled_by INTEGER REFERENCES users(id),
    created_at TIMESTAMP DEFAULT now(),
    updated_at TIMESTAMP
);
"""


def init_db(conn: duckdb.DuckDBPyConnection) -> None:
    with _lock:
        for stmt in [s.strip() for s in SCHEMA.split(";") if s.strip()]:
            conn.execute(stmt)
        if conn.execute("SELECT count(*) FROM users").fetchone()[0] == 0:
            seed(conn)
        # 种子数据占用小 id，用户新增记录从 1000 开始避免主键冲突
        for seq in ("seq_users", "seq_plots", "seq_batches", "seq_adoptions",
                    "seq_weather_events", "seq_resolutions",
                    "seq_picking_records", "seq_after_sales"):
            # DuckDB 不支持 ALTER SEQUENCE/setval，用 nextval 推进到 999
            conn.execute(f"SELECT nextval('{seq}') FROM range(999)")


def seed(conn: duckdb.DuckDBPyConnection) -> None:
    from .security import hash_password

    def ins(sql: str, params: list) -> int:
        cur = conn.execute(sql + " RETURNING id", params)
        return int(cur.fetchone()[0])

    admin = ins("INSERT INTO users (username,password_hash,display_name,role,phone) VALUES (?,?,?,?,?)",
                ["admin", hash_password("admin123"), "平台管理员", "admin", "010-88888888"])
    f1 = ins("INSERT INTO users (username,password_hash,display_name,role,phone,address) VALUES (?,?,?,?,?,?)",
             ["laowang", hash_password("farmer123"), "老王果园", "farmer", "13800000001", "山东烟台"])
    f2 = ins("INSERT INTO users (username,password_hash,display_name,role,phone,address) VALUES (?,?,?,?,?,?)",
             ["ajing", hash_password("farmer123"), "阿静茶场", "farmer", "13800000002", "浙江杭州"])
    f3 = ins("INSERT INTO users (username,password_hash,display_name,role,phone,address) VALUES (?,?,?,?,?,?)",
             ["laoli", hash_password("farmer123"), "老李生态农场", "farmer", "13800000003", "山东寿光"])
    c1 = ins("INSERT INTO users (username,password_hash,display_name,role,phone,address) VALUES (?,?,?,?,?,?)",
             ["xiaoming", hash_password("consumer123"), "小明", "consumer", "13900000001", "北京市朝阳区"])
    c2 = ins("INSERT INTO users (username,password_hash,display_name,role,phone,address) VALUES (?,?,?,?,?,?)",
             ["xiaohong", hash_password("consumer123"), "小红", "consumer", "13900000002", "上海市浦东新区"])
    c3 = ins("INSERT INTO users (username,password_hash,display_name,role,phone,address) VALUES (?,?,?,?,?,?)",
             ["xiaogang", hash_password("consumer123"), "小刚", "consumer", "13900000003", "广州市天河区"])

    p1 = ins("INSERT INTO plots (farmer_id,name,crop_type,crop_name,location,area_mu,description) VALUES (?,?,?,?,?,?,?)",
             [f1, "老王烟台苹果园 A 区", "orchard", "红富士苹果", "山东烟台栖霞", 20.0,
              "向阳坡地，20 年树龄红富士，脆甜多汁。"])
    p2 = ins("INSERT INTO plots (farmer_id,name,crop_type,crop_name,location,area_mu,description) VALUES (?,?,?,?,?,?,?)",
             [f1, "老王砀山酥梨园", "orchard", "砀山酥梨", "安徽砀山", 12.0,
              "黄河故道沙壤土，皮薄肉脆。"])
    p3 = ins("INSERT INTO plots (farmer_id,name,crop_type,crop_name,location,area_mu,description) VALUES (?,?,?,?,?,?,?)",
             [f2, "阿静西湖龙井茶田", "tea", "西湖龙井（明前）", "浙江杭州西湖区", 8.0,
              "核心产区群体种，明前手工采摘。"])
    p4 = ins("INSERT INTO plots (farmer_id,name,crop_type,crop_name,location,area_mu,description) VALUES (?,?,?,?,?,?,?)",
             [f3, "老李有机蔬菜大棚", "vegetable", "时令有机蔬菜", "山东寿光", 15.0,
              "有机认证，不打化学农药，应季叶菜瓜果。"])

    def batch(plot_id, name, season, slots, price, yld, s, e, delivery, status="open", ws="normal"):
        return ins("""INSERT INTO batches
            (plot_id,name,season,total_slots,unit_price,yield_desc,pickup_start,pickup_end,delivery_options,status,weather_status)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                   [plot_id, name, season, slots, price, yld, s, e, delivery, status, ws])

    b1 = batch(p1, "2026 红富士认养季", "2026 秋季", 50, 299.0, "约 20 斤苹果/份",
               "2026-10-15", "2026-11-15", "self_pickup,platform_delivery,farm_ship", "open", "affected")
    b2 = batch(p3, "2027 明前龙井认养", "2027 春季", 30, 680.0, "约 1 斤明前干茶/份",
               "2027-03-20", "2027-04-10", "platform_delivery,farm_ship")
    b3 = batch(p4, "2026 秋冬蔬菜包认养", "2026 秋冬季", 80, 158.0, "约 10 斤时令蔬菜/份",
               "2026-10-01", "2026-12-20", "self_pickup,platform_delivery")
    b4 = batch(p2, "2026 砀山梨认养季", "2026 秋季", 40, 199.0, "约 15 斤酥梨/份",
               "2026-09-10", "2026-10-10", "self_pickup,farm_ship")

    def adoption(batch_id, user, slots, date, mode, addr, status, name, phone):
        return ins("""INSERT INTO adoptions
            (batch_id,consumer_id,slots,amount,scheduled_date,delivery_mode,delivery_address,contact_name,contact_phone,status,picked_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                   [batch_id, user, slots,
                    slots * {b1: 299.0, b2: 680.0, b3: 158.0, b4: 199.0}[batch_id],
                    date, mode, addr, name, phone, status,
                    "2026-09-20 09:30:00" if status == "picked" else None])

    a1 = adoption(b1, c1, 2, "2026-10-20", "platform_delivery", "北京市朝阳区建国路 88 号", "booked", "小明", "13900000001")
    a2 = adoption(b1, c2, 1, "2026-10-25", "farm_ship", "上海市浦东新区世纪大道 100 号", "booked", "小红", "13900000002")
    a3 = adoption(b3, c3, 3, "2026-10-05", "self_pickup", None, "booked", "小刚", "13900000003")
    a4 = adoption(b4, c3, 1, "2026-09-20", "self_pickup", None, "picked", "小刚", "13900000003")
    a5 = adoption(b3, c1, 2, "2026-10-12", "platform_delivery", "北京市朝阳区建国路 88 号", "picked", "小明", "13900000001")
    a6 = adoption(b4, c2, 2, "2026-09-25", "self_pickup", None, "picked", "小红", "13900000002")

    ev1 = ins("""INSERT INTO weather_events (batch_id,event_type,severity,yield_impact_pct,event_date,description,status,created_by)
        VALUES (?,?,?,?,?,?,?,?)""",
              [b1, "hail", "moderate", 30, "2026-09-28",
               "9 月 28 日午后冰雹，部分果面受伤，预计减产约三成，建议采摘延后 7-10 天。", "open", f1])

    ins("INSERT INTO resolutions (adoption_id,event_id,option,new_date,new_batch_id,refund_amount,note,status) VALUES (?,?,?,?,?,?,?,?)",
        [a1, ev1, "reschedule", "2026-10-30", None, None, "建议改期至 10 月 30 日，果实恢复后采摘。", "pending"])
    ins("INSERT INTO resolutions (adoption_id,event_id,option,new_date,new_batch_id,refund_amount,note,status) VALUES (?,?,?,?,?,?,?,?)",
        [a1, ev1, "refund", None, None, 598.0, "按实付金额全额退款 598 元。", "pending"])
    ins("INSERT INTO resolutions (adoption_id,event_id,option,new_date,new_batch_id,refund_amount,note,status) VALUES (?,?,?,?,?,?,?,?)",
        [a1, ev1, "swap", None, b4, None, "可换至「砀山酥梨 2026 秋季批次」。", "pending"])
    ins("INSERT INTO resolutions (adoption_id,event_id,option,new_date,new_batch_id,refund_amount,note,status) VALUES (?,?,?,?,?,?,?,?)",
        [a2, ev1, "reschedule", "2026-11-03", None, None, "建议改期至 11 月 3 日。", "pending"])
    ins("INSERT INTO resolutions (adoption_id,event_id,option,new_date,new_batch_id,refund_amount,note,status) VALUES (?,?,?,?,?,?,?,?)",
        [a2, ev1, "refund", None, None, 299.0, "按实付金额退款 299 元。", "pending"])
    ins("INSERT INTO resolutions (adoption_id,event_id,option,new_date,new_batch_id,refund_amount,note,status) VALUES (?,?,?,?,?,?,?,?)",
        [a2, ev1, "swap", None, b4, None, "可换至「砀山酥梨 2026 秋季批次」。", "pending"])

    conn.execute("""INSERT INTO picking_records (adoption_id,picked_by,picked_date,weight_kg,note)
        VALUES (?,?,?,?,?)""", [a4, f3, "2026-09-20", 16.2, "果个均匀，消费者现场满意。"])
    conn.execute("""INSERT INTO picking_records (adoption_id,picked_by,picked_date,weight_kg,note)
        VALUES (?,?,?,?,?)""", [a5, f3, "2026-10-12", 21.5, "两份蔬菜包一次取走。"])
    conn.execute("""INSERT INTO picking_records (adoption_id,picked_by,picked_date,weight_kg,note)
        VALUES (?,?,?,?,?)""", [a6, f1, "2026-09-25", 31.0, "酥梨两份，快递箱包装。"])

    ins("INSERT INTO after_sales (adoption_id,consumer_id,issue_type,content,status) VALUES (?,?,?,?,?)",
        [a6, c2, "quality", "收到的酥梨有 2 个碰伤，希望补寄或补偿。", "open"])
    ins("INSERT INTO after_sales (adoption_id,consumer_id,issue_type,content,status,reply,handled_by,updated_at) VALUES (?,?,?,?,?,?,?,?)",
        [a5, c1, "delivery", "配送比约定晚了半天，菜有点发蔫。", "replied",
         "已联系配送方改进，补偿 20 元无门槛券，请注意查收。", admin, "2026-10-13 10:00:00"])
