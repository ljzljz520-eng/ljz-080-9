"""演示数据：3 户农户 / 3 类地块 / 5 个批次 / 认养 / 天气事件 / 售后。可重复执行。"""
from __future__ import annotations

from datetime import date

from . import db, services
from .schema import init_schema

SEQS = ["seq_farmers", "seq_plots", "seq_batches", "seq_adoptions", "seq_weather", "seq_aftersales"]


def reset() -> None:
    from .schema import SEQUENCES
    with db.transaction() as conn:
        # 先按依赖逆序删表（CASCADE 保险），再删序列，最后整体重建
        for table in ["after_sales", "adoptions", "weather_events", "batches", "plots", "farmers"]:
            conn.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
        for name in SEQS:
            conn.execute(f"DROP SEQUENCE IF EXISTS {name}")
    init_schema()


def run() -> None:
    reset()
    ts = db.now_iso()

    # ---- 农户 ----
    f1 = services.create_farmer("陈德顺", "13900000001", "东山顺达果园", "江苏苏州吴中区东山镇")
    f2 = services.create_farmer("周婉清", "13900000002", "安吉婉清白茶园", "浙江湖州安吉县溪龙乡")
    f3 = services.create_farmer("李秀兰", "13900000003", "昆城兰姐有机农场", "江苏昆山张浦镇")

    # ---- 地块 ----
    p1 = services.create_plot(f1, "orchard", "洞庭山三号橘园", "东山镇碧螺村东坡", 12.0, 30,
                              "坡地向阳，灌溉水源为山泉水，主种晚熟蜜橘。")
    p2 = services.create_plot(f2, "tea_garden", "溪龙核心区白茶田", "安吉县溪龙乡黄杜村", 30.0, 50,
                              "核心产区白化茶，明前头采一芽一叶。")
    p3 = services.create_plot(f3, "vegetable_field", "张浦二号露天菜地", "昆山张浦镇金华村", 8.0, 40,
                              "露天轮作菜地，应季叶菜与根茎类。")

    # ---- 认养批次（按插入顺序 id 1..5）----
    services.create_batch(p1, "洞庭晚熟蜜橘", "斤", 200, 12.8, "2026-10-10", "2026-11-20")   # 1
    services.create_batch(p1, "碧螺村砂糖橘", "斤", 200, 9.9, "2026-11-01", "2026-12-15")    # 2
    services.create_batch(p2, "明前安吉白茶", "盒(250g)", 200, 188.0, "2027-03-15", "2027-04-10")  # 3
    services.create_batch(p3, "秋冬矮脚青", "斤", 50, 4.5, "2026-09-20", "2026-10-25")       # 4
    services.create_batch(p3, "沙地红薯", "斤", 100, 6.0, "2026-10-01", "2026-11-10")        # 5

    # ---- 认养订单（批次1、2、4、5 各有认养）----
    adoptions = [
        # batch, name, phone, units, pickup, delivery, address, status
        (1, "王磊", "13800000001", 20, "2026-10-18", "self_pick", "", "scheduled"),
        (1, "赵敏", "13800000002", 20, "2026-10-25", "express", "上海市浦东新区张江路 100 号", "scheduled"),
        (2, "王磊", "13800000001", 10, "2026-11-08", "logistics", "园区自提点", "scheduled"),
        (4, "孙倩", "13800000003", 8, "2026-09-28", "self_pick", "", "picked"),
        (4, "赵强", "13800000004", 2, "2026-09-26", "logistics", "昆山花桥自提点", "completed"),
        (5, "陈晨", "13800000005", 20, "2026-10-12", "express", "杭州市西湖区文三路 88 号", "scheduled"),
        (5, "林楠", "13800000006", 10, "2026-10-15", "self_pick", "", "scheduled"),
    ]
    with db.transaction() as conn:
        for batch_id, name, phone, units, pickup, delivery, addr, status in adoptions:
            price = conn.execute("SELECT price_per_unit FROM batches WHERE id=?", [batch_id]).fetchone()[0]
            conn.execute(
                """INSERT INTO adoptions(batch_id, customer_name, customer_phone, units, amount,
                       pickup_date, delivery, address, status, created_at, updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                [batch_id, name, phone, units, round(units * price, 2), pickup, delivery, addr, status, ts, ts],
            )
            conn.execute("UPDATE batches SET remaining_units = remaining_units - ? WHERE id=?", [units, batch_id])

    # ---- 天气事件：批次5（红薯）连阴雨，挂起两笔待处理订单 ----
    with db.transaction() as conn:
        cur = conn.execute(
            """INSERT INTO weather_events(batch_id, event_date, kind, impact, yield_loss_pct,
                   description, status, created_at)
               VALUES(5, ?, 'rain', '预计减产约三成', 30,
                       '10月初持续降雨导致薯田积水，采挖推迟。', 'active', ?) RETURNING id""",
            [str(date(2026, 9, 28)), ts],
        )
        wid = int(cur.fetchone()[0])
        conn.execute(
            "UPDATE adoptions SET weather_id=? WHERE batch_id=5 AND status='scheduled'", [wid]
        )

    # ---- 售后 ----
    with db.transaction() as conn:
        conn.execute(
            """INSERT INTO after_sales(adoption_id, kind, description, status, created_at, updated_at)
               VALUES(4,'shortage','自提称重少了约 1 斤，希望核实。','open',?,?)""",
            [ts, ts],
        )
        conn.execute(
            """INSERT INTO after_sales(adoption_id, kind, description, status, reply, created_at, updated_at)
               VALUES(5,'delay','集中配送晚了两天，菜叶有点蔫。','resolved','已补发一斤并赠送下期优惠券。',?,?)""",
            [ts, ts],
        )

    # ---- 推导各批次状态 ----
    for i in range(1, 6):
        services.recompute_batch_status(i)


def seed_if_empty() -> None:
    init_schema()
    row = db.fetchone("SELECT COUNT(*) AS c FROM farmers")
    if row["c"] == 0:
        run()


if __name__ == "__main__":
    run()
    print("seed done")
