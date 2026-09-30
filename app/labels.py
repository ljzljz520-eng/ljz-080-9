"""中文标签与选项常量。"""

CROP_TYPES = {
    "orchard": "果园",
    "tea": "茶田",
    "vegetable": "菜地",
}
CROP_ICONS = {"orchard": "🍑", "tea": "🍵", "vegetable": "🥬"}

BATCH_STATUS = {
    "open": "认养中",
    "full": "已约满",
    "closed": "已结束",
}
BATCH_WEATHER_STATUS = {
    "normal": "正常",
    "affected": "受天气影响",
    "resolved": "影响已处理",
}

ADOPTION_STATUS = {
    "booked": "待采摘",
    "picked": "已采摘",
    "rescheduled": "已改期",
    "refunded": "已退款",
    "swapped": "已换批",
    "cancelled": "已取消",
}

DELIVERY_MODES = {
    "self_pickup": "到园自提",
    "platform_delivery": "平台配送",
    "farm_ship": "农户快递",
}

EVENT_TYPES = {
    "frost": "霜冻",
    "hail": "冰雹",
    "drought": "干旱",
    "flood": "洪涝",
    "typhoon": "台风",
    "heatwave": "高温",
    "pest": "病虫害",
    "other": "其他",
}
SEVERITY = {"minor": "轻微", "moderate": "中等", "severe": "严重"}

EVENT_STATUS = {"open": "待处理", "resolved": "已处理"}
RESOLUTION_STATUS = {"pending": "待消费者选择", "accepted": "已接受"}
RESOLUTION_TYPES = {
    "reschedule": "改期",
    "refund": "退款",
    "swap": "换批次",
}

AFTERSALE_STATUS = {
    "open": "待处理",
    "replied": "已回复",
    "closed": "已关闭",
}
AFTERSALE_TYPES = {
    "quality": "品质问题",
    "delivery": "配送问题",
    "schedule": "采摘安排",
    "other": "其他",
}

BADGE_CLASS = {
    # batch status
    "open": "badge badge-green",
    "full": "badge badge-amber",
    "closed": "badge badge-gray",
    "normal": "badge badge-green",
    "affected": "badge badge-red",
    "resolved": "badge badge-blue",
    # adoption status
    "booked": "badge badge-blue",
    "picked": "badge badge-green",
    "rescheduled": "badge badge-amber",
    "refunded": "badge badge-gray",
    "swapped": "badge badge-purple",
    "cancelled": "badge badge-gray",
    # event / aftersale
    "minor": "badge badge-amber",
    "moderate": "badge badge-orange",
    "severe": "badge badge-red",
    "pending": "badge badge-amber",
    "accepted": "badge badge-green",
    "replied": "badge badge-blue",
}
