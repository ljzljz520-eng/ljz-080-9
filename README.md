# 🌱 绿野认养 · 农产品预售采摘认养平台

农户发布**果园 / 茶田 / 菜地**的认养批次，消费者选择地块、采摘时间与配送方式进行预售认养；
当霜冻、冰雹、干旱等天气影响产量时，平台为每位消费者自动生成 **改期 / 退款 / 换批次** 三种方案；
管理端可查看每块地的认养人数、采摘进度与售后问题。

技术栈：**FastAPI + Jinja2 服务端渲染 + DuckDB（单文件嵌入式数据库）**，无需外部服务。

## 快速开始

```bash
pip install -r requirements.txt
./run.sh                 # 或 python3 -m uvicorn app.main:app --port 8000
# 打开 http://localhost:8000
```

首次启动会自动建表并写入演示数据（DuckDB 文件位于 `data/farm.db`，删除即可重置）。

### 演示账号

| 角色 | 用户名 | 密码 |
| --- | --- | --- |
| 管理员 | `admin` | `admin123` |
| 农户（老王果园） | `laowang` | `farmer123` |
| 农户（阿静茶场） | `ajing` | `farmer123` |
| 农户（老李蔬菜） | `laoli` | `farmer123` |
| 消费者 | `xiaoming` / `xiaohong` / `xiaogang` | `consumer123` |

## 业务流程

1. **农户**：发布地块（类型/品种/位置/面积）→ 发布认养批次（总份数、单价、采摘区间、支持自提/平台配送/农户快递）
   → 在批次页**上报天气事件**（类型、程度、减产比例、说明），系统为每个待采摘认养自动生成三种应对方案
   → 采摘日**登记采摘**（重量、备注），订单变为「已采摘」。
2. **消费者**：浏览地块/批次 → 选择份数、计划采摘日期、配送方式下单 → 在「我的认养」查看订单；
   批次受天气影响时收到提示，进入方案页**三选一**（改期更新预约日期 / 退款按实付退回 / 换批次自动生成新订单）；
   可发起品质、配送、排期类**售后**。
3. **管理员**：经营总览（地块认养人数、认养/采摘份数进度条、待处理售后与天气事件）
   → 地块详情（批次进度 + 售后清单）→ 回复/关闭售后工单 → 监督天气事件，全部消费者选择完成后关闭事件。

## 数据模型（DuckDB）

- `users` 用户（admin / farmer / consumer，PBKDF2 密码哈希）
- `plots` 地块（果园 orchard / 茶田 tea / 菜地 vegetable）
- `batches` 认养批次（份数、价格、采摘期、配送方式、业务状态、天气状态）
- `adoptions` 认养订单（份数、金额、预约日期、配送方式、订单状态）
- `weather_events` 天气/产量影响事件
- `resolutions` 每个订单的改期/退款/换批方案及消费者选择
- `picking_records` 采摘登记记录
- `after_sales` 售后工单与平台回复

## 目录结构

```
app/
  main.py            # 应用入口、中间件、异常处理
  db.py              # DuckDB 连接、建表、种子数据
  security.py        # PBKDF2 密码哈希
  common.py          # 会话、模板、闪现消息、角色依赖
  labels.py          # 中文标签/徽章常量
  routers/           # pages(公开) / auth / consumer / farmer / admin
  templates/         # Jinja2 模板（base + 各角色页面）
static/style.css     # 样式
run.sh               # 启动脚本
```

## 说明

- 会话使用 itsdangerous 签名的 HttpOnly Cookie；服务重启无需额外配置。
- 下单、退款、换批次等涉及库存的操作使用事务 + 全局连接锁，避免超卖。
