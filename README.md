# 🌱 绿野认养 · 农产品预售采摘认养平台

农户发布**果园 / 茶田 / 菜地**的认养批次，消费者选择**地块、采摘时间、配送方式**进行预售认养；
当天气影响产量时，平台自动为受影响订单提供 **改期 / 退款 / 换批次** 三种处置；
管理端可查看**每块地的认养人数、采摘进度、售后问题**。

技术栈：**FastAPI + Jinja2 服务端渲染 + DuckDB 持久化**（同一套 services 层同时支撑页面表单与 JSON API）。

## 快速开始

```bash
pip install -r requirements.txt
python run.py                 # http://127.0.0.1:8000
```

- 首次启动自动建表并写入演示数据（3 农户 / 3 地块 / 5 批次 / 认养 / 天气事件 / 售后）
- 重置演示数据：`python -m app.seed`
- 数据库文件：`app/farmpresale.duckdb`（删除后重启即全新库）

## 页面入口

| 入口 | 地址 | 说明 |
|---|---|---|
| 认养首页 | `/` | 可认养批次、剩余量、档期；进入详情下单 |
| 批次详情 | `/batches/{id}` | 选数量 / 采摘日期 / 配送方式（自提·冷链快递·集中配送点） |
| 我的认养 | `/my?phone=手机号` | 订单状态；天气挂起时显示**改期 / 退款 / 换批次**三选一；申请售后 |
| 农户工作台 | `/farmer` | 发布地块与批次、登记天气影响、订单采摘登记与核销、解除预警 |
| 农户批次管理 | `/farmer/batches/{id}` | 认养名单、采摘进度、逐个核销 |
| 管理总览 | `/admin` | 平台指标、**每块地认养人数 / 采摘进度 / 售后数**、天气预警 |
| 地块详情 | `/admin/plots/{id}` | 单地块的认养、采摘、售后明细 |
| 售后中心 | `/admin/after-sales` | 待处理 / 处理中 / 已解决 流转与回复 |

## JSON API（示例）

```bash
# 认养
curl -X POST localhost:8000/api/adoptions -H 'Content-Type: application/json' -d '{
  "batch_id":1,"customer_name":"张三","customer_phone":"138...",
  "units":10,"pickup_date":"2026-10-20","delivery":"express","address":"..."}'

# 天气影响（农户登记后，相关订单自动挂起）
POST /api/weather
# 消费者选择：reschedule（带 new_pickup_date）/ refund / transfer（带 new_batch_id）
POST /api/adoptions/{id}/resolve
# 采摘核销两步：登记采摘 -> 核销完成
POST /api/adoptions/{id}/pick
POST /api/adoptions/{id}/complete
# 售后：提交 / 列表 / 流转
POST /api/after-sales   GET /api/after-sales   PATCH /api/after-sales/{id}
# 管理端总览
GET /api/admin/overview
```

完整接口见 `app/routers/api.py`（OpenAPI 文档 `/docs`）。

## 业务规则

- **认养校验**：批次未受天气影响/未结束、采摘日在档期内、数量不超剩余库存、地块认养人数不超上限；金额 = 数量 × 单价（服务端计算）。
- **天气处置**：登记天气事件后批次变为「天气影响」并停止新认养，有效订单挂起；客户三选一：
  - 改期：在原批次档期内另选日期；
  - 退款：订单关闭、库存释放；
  - 换批次：库存双向调整，金额按新批次单价多退少补。
  - 预警解除时，未做选择的订单自动恢复正常预约。
- **采摘进度**：`已采摘(含已核销) / 有效认养量`；订单状态机 scheduled → picked → completed，退款/改期/换批次各自独立状态。
- **售后**：消费者按订单发起（品质/缺斤少两/配送延误/其他），管理端 open → processing → resolved 并回复。
- **批次状态**：`open / affected / full / closed` 由天气事件、剩余库存、档期结束日期自动推导。

## 目录结构

```
app/
  main.py          # FastAPI 入口、Jinja2 配置、启动自动播种
  db.py            # DuckDB 连接、查询助手、写事务（进程锁）
  schema.py        # 建表 DDL + 序列 + 索引
  seed.py          # 演示数据（可重复执行，清库重建）
  services.py      # 全部业务规则（页面与 API 共用）
  labels.py        # 状态/类型中文标签与配色
  models.py        # API 请求 Pydantic 模型
  routers/
    pages.py       # Jinja2 页面与表单路由（POST-redirect-GET + flash）
    api.py         # JSON API
  templates/       # base/index/batch_detail/my/farmer*/admin/plot_detail/after_sales
  static/style.css
```

> 说明：DuckDB 1.5 在更新「被子表引用的外键列」时会触发即时引用检查
> （`SET foreign_keys_check` 亦不支持关闭），因此关联完整性由 services 层的
> 存在性校验 + 写事务保证，DDL 中仅保留主键/唯一约束与索引。
