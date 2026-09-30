"""建表 DDL 与序列。DuckDB 0.10+ 原生支持 SEQUENCE。"""

SEQUENCES = [
    "CREATE SEQUENCE IF NOT EXISTS seq_farmers START 1",
    "CREATE SEQUENCE IF NOT EXISTS seq_plots START 1",
    "CREATE SEQUENCE IF NOT EXISTS seq_batches START 1",
    "CREATE SEQUENCE IF NOT EXISTS seq_adoptions START 1",
    "CREATE SEQUENCE IF NOT EXISTS seq_weather START 1",
    "CREATE SEQUENCE IF NOT EXISTS seq_aftersales START 1",
]

TABLES = [
    """
    CREATE TABLE IF NOT EXISTS farmers (
        id          INTEGER PRIMARY KEY DEFAULT nextval('seq_farmers'),
        name        VARCHAR NOT NULL,
        phone       VARCHAR NOT NULL,
        farm_name   VARCHAR NOT NULL,
        region      VARCHAR NOT NULL,
        created_at  VARCHAR NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS plots (
        id           INTEGER PRIMARY KEY DEFAULT nextval('seq_plots'),
        farmer_id    INTEGER NOT NULL,
        plot_type    VARCHAR NOT NULL,   -- orchard 果园 / tea_garden 茶田 / vegetable_field 菜地
        name         VARCHAR NOT NULL,
        location     VARCHAR NOT NULL,
        area_mu      DOUBLE NOT NULL,
        capacity     INTEGER NOT NULL,   -- 认养人数上限
        description  VARCHAR,
        created_at   VARCHAR NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS batches (
        id              INTEGER PRIMARY KEY DEFAULT nextval('seq_batches'),
        plot_id         INTEGER NOT NULL,
        batch_no        VARCHAR NOT NULL UNIQUE,
        produce_name    VARCHAR NOT NULL,
        unit            VARCHAR NOT NULL,        -- 斤 / 盒
        total_units     DOUBLE NOT NULL,         -- 预计总产量
        remaining_units DOUBLE NOT NULL,         -- 剩余可认养量
        price_per_unit  DOUBLE NOT NULL,
        season_start    DATE NOT NULL,
        season_end      DATE NOT NULL,
        status          VARCHAR NOT NULL DEFAULT 'open',
        -- open 认养中 / affected 受天气影响 / full 已认满 / closed 已结束
        created_at      VARCHAR NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS weather_events (
        id           INTEGER PRIMARY KEY DEFAULT nextval('seq_weather'),
        batch_id     INTEGER NOT NULL,
        event_date   DATE NOT NULL,
        kind         VARCHAR NOT NULL,  -- frost 倒春寒 / drought 干旱 / rain 连阴雨 / storm 冰雹大风 / heat 高温
        impact       VARCHAR NOT NULL,  -- 减产比例描述
        yield_loss_pct INTEGER NOT NULL,
        description  VARCHAR,
        status       VARCHAR NOT NULL DEFAULT 'active',  -- active 处置中 / resolved 已解除
        created_at   VARCHAR NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS adoptions (
        id             INTEGER PRIMARY KEY DEFAULT nextval('seq_adoptions'),
        batch_id       INTEGER NOT NULL,
        customer_name  VARCHAR NOT NULL,
        customer_phone VARCHAR NOT NULL,
        units          DOUBLE NOT NULL,
        amount         DOUBLE NOT NULL,
        pickup_date    DATE NOT NULL,
        delivery       VARCHAR NOT NULL,  -- self_pick 到园自提 / express 冷链快递 / logistics 集中配送
        address        VARCHAR,
        status         VARCHAR NOT NULL DEFAULT 'scheduled',
        -- scheduled 已预约 / picked 已采摘 / completed 已完成(核销送达)
        -- / rescheduled 已改期 / refunded 已退款 / transferred 已换批次 / cancelled 已取消
        resolution     VARCHAR,           -- 天气售后选择：reschedule/refund/transfer
        new_pickup_date DATE,
        new_batch_id   INTEGER,
        weather_id     INTEGER,
        created_at     VARCHAR NOT NULL,
        updated_at     VARCHAR NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS after_sales (
        id           INTEGER PRIMARY KEY DEFAULT nextval('seq_aftersales'),
        adoption_id  INTEGER NOT NULL,
        kind         VARCHAR NOT NULL,  -- quality 品质问题 / shortage 缺斤少两 / delay 配送延误 / other 其他
        description  VARCHAR NOT NULL,
        status       VARCHAR NOT NULL DEFAULT 'open',  -- open 待处理 / processing 处理中 / resolved 已解决
        reply        VARCHAR,
        created_at   VARCHAR NOT NULL,
        updated_at   VARCHAR NOT NULL
    )
    """,
]

INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_plots_farmer ON plots(farmer_id)",
    "CREATE INDEX IF NOT EXISTS idx_batches_plot ON batches(plot_id)",
    "CREATE INDEX IF NOT EXISTS idx_adoptions_batch ON adoptions(batch_id)",
    "CREATE INDEX IF NOT EXISTS idx_aftersales_adoption ON after_sales(adoption_id)",
    "CREATE INDEX IF NOT EXISTS idx_weather_batch ON weather_events(batch_id)",
]


def init_schema() -> None:
    from . import db

    for ddl in SEQUENCES + TABLES + INDEXES:
        db.execute(ddl)
