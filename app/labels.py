"""集中管理状态中文标签，供 Python 与 Jinja 模板共用。"""

PLOT_TYPES = {
    "orchard": "果园",
    "tea_garden": "茶田",
    "vegetable_field": "菜地",
}

BATCH_STATUS = {
    "open": "认养中",
    "affected": "天气影响",
    "full": "已认满",
    "closed": "已结束",
}

ADOPTION_STATUS = {
    "scheduled": "已预约",
    "picked": "已采摘",
    "completed": "已完成",
    "rescheduled": "已改期",
    "refunded": "已退款",
    "transferred": "已换批次",
    "cancelled": "已取消",
}

DELIVERY = {
    "self_pick": "到园自提",
    "express": "冷链快递",
    "logistics": "集中配送点",
}

WEATHER_KIND = {
    "frost": "倒春寒/霜冻",
    "drought": "干旱",
    "rain": "连阴雨",
    "storm": "冰雹大风",
    "heat": "持续高温",
}

WEATHER_STATUS = {"active": "处置中", "resolved": "已解除"}

AFTERSALE_KIND = {
    "quality": "品质问题",
    "shortage": "缺斤少两",
    "delay": "配送延误",
    "other": "其他",
}

AFTERSALE_STATUS = {"open": "待处理", "processing": "处理中", "resolved": "已解决"}

RESOLUTION = {"reschedule": "改期采摘", "refund": "退款", "transfer": "换批次"}

BADGE = {
    "open": "green", "resolved": "gray", "full": "blue", "closed": "gray",
    "affected": "red", "active": "red", "scheduled": "blue", "picked": "amber",
    "completed": "green", "rescheduled": "amber", "refunded": "gray",
    "transferred": "purple", "cancelled": "gray",
    "processing": "amber",
}
