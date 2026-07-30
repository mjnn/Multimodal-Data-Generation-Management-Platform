"""One-off generator for shared/config/oms_enum_zh.yaml."""
from __future__ import annotations

import yaml
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TAXONOMY = REPO / "shared" / "config" / "oms_label_taxonomy.yaml"
OUT = REPO / "shared" / "config" / "oms_enum_zh.yaml"

ZH: dict[str, str] = {
    "dawn": "凌晨",
    "morning": "上午",
    "noon": "中午",
    "afternoon": "下午",
    "dusk": "傍晚",
    "evening": "晚上",
    "night": "夜间",
    "morning_commute": "早高峰通勤",
    "evening_commute": "晚高峰通勤",
    "non_commute": "非通勤",
    "true": "是",
    "false": "否",
    "natural": "自然光",
    "artificial": "人工光",
    "mixed": "混合光",
    "sunny": "晴",
    "cloudy": "多云",
    "overcast": "阴",
    "light_rain": "小雨",
    "heavy_rain": "大雨",
    "snow": "雪",
    "fog": "雾",
    "dust_storm": "沙尘暴",
    "parked": "驻车",
    "idling": "怠速",
    "urban_low": "城区低速",
    "urban_high": "城区高速",
    "expressway": "快速路/高速",
    "traffic_jam": "拥堵",
    "off_road": "非铺装/越野",
    "P": "P档",
    "R": "R档",
    "N": "N档",
    "D": "D档",
    "M": "M档",
    "highway": "高速公路",
    "urban_arterial": "城市主干道",
    "local_street": "地方道路",
    "rural": "乡村道路",
    "parking_lot": "停车场",
    "unknown": "未知",
    "none": "无",
    "2d_rgb": "2D RGB",
    "2d_ir": "2D 红外",
    "3d_tof": "3D ToF",
    "stereo_ir": "立体红外",
    "registered": "已注册",
    "guest": "访客",
    "infant": "婴儿",
    "child": "儿童",
    "teen": "青少年",
    "adult": "成人",
    "senior": "老年",
    "driver": "驾驶员",
    "front_passenger": "副驾",
    "rear_left": "后排左",
    "rear_center": "后排中",
    "rear_right": "后排右",
    "rear_third": "第三排",
    "alert": "清醒",
    "mild_fatigue": "轻度疲劳",
    "moderate_fatigue": "中度疲劳",
    "severe_fatigue": "重度疲劳",
    "neutral": "中性",
    "happy": "高兴",
    "sad": "悲伤",
    "angry": "愤怒",
    "surprised": "惊讶",
    "fearful": "恐惧",
    "disgusted": "厌恶",
    "road_ahead": "前方道路",
    "left_mirror": "左后视镜",
    "right_mirror": "右后视镜",
    "rear_mirror": "内后视镜",
    "instrument_cluster": "仪表",
    "center_screen": "中控屏",
    "left_window": "左侧窗",
    "right_window": "右侧窗",
    "passenger": "乘员",
    "phone": "手机",
    "other": "其他",
    "attentive": "专注",
    "slight_distraction": "轻度分心",
    "moderate_distraction": "中度分心",
    "severe_distraction": "重度分心",
    "phone_use": "使用手机",
    "eating_drinking": "饮食",
    "infotainment": "娱乐系统",
    "adjusting_controls": "调节控件",
    "passenger_interaction": "与乘员互动",
    "adjusting_clothing": "整理衣物",
    "ask_confirm": "询问确认",
    "beverage": "饮料",
    "book": "书籍",
    "both": "双向",
    "brow_furrow": "皱眉",
    "buckling_seatbelt": "系安全带",
    "casual_chat_with_hmi": "与 HMI 闲聊",
    "child_care": "照看儿童",
    "cigarette": "香烟",
    "clear_throat": "清嗓",
    "climate_ui": "空调界面",
    "condition_trigger": "条件触发",
    "cough": "咳嗽",
    "cry": "哭泣",
    "deferred": "延后",
    "driving": "驾驶中",
    "drinking": "饮水",
    "eating": "进食",
    "eating_while_driving": "驾驶中进食",
    "execute_directly": "直接执行",
    "external_event": "外部事件",
    "eye_wide": "睁大眼",
    "failed": "失败",
    "food": "食物",
    "frown": "不悦",
    "groan": "呻吟",
    "holding_child": "抱儿童",
    "human_to_human": "人人对话",
    "humming": "哼唱",
    "hmi_command": "HMI 指令",
    "laugh": "笑",
    "mouth_open": "张嘴",
    "lip_press": "抿嘴",
    "makeup": "化妆",
    "music_player": "音乐播放器",
    "nav_instruction": "导航播报",
    "nav_map": "导航地图",
    "newspaper": "报纸",
    "no_hands": "双手离盘",
    "no_seatbelt": "未系安全带",
    "notification": "通知",
    "partial_success": "部分成功",
    "pet": "宠物",
    "petting": "抚摸宠物",
    "phone_call": "打电话",
    "phone_calling": "通话中",
    "phone_ui": "手机界面",
    "phone_using": "使用手机",
    "phone_while_driving": "驾驶中使用手机",
    "proactive_push": "主动推送",
    "reading": "阅读",
    "rejected": "已拒绝",
    "resting_sleeping": "休息/睡觉",
    "scheduled": "已计划",
    "seat_vibration": "座椅振动",
    "settings": "设置",
    "sigh": "叹气",
    "silence": "沉默",
    "silent_execute": "静默执行",
    "singing": "唱歌",
    "sneeze": "打喷嚏",
    "smile": "微笑",
    "smoking": "吸烟",
    "solo_talking_to_self": "独自说话",
    "steering_vibration": "方向盘振动",
    "success": "成功",
    "system_proactive": "系统主动",
    "timeout": "超时",
    "tissue": "纸巾",
    "toast": "提示",
    "toy": "玩具",
    "user_command": "用户指令",
    "yawn_sound": "打哈欠",
}


def main() -> None:
    data = yaml.safe_load(TAXONOMY.read_text(encoding="utf-8"))
    needed: set[str] = set()
    for item in data["labels"]:
        schema = item.get("value_schema") or {}
        if schema.get("type") == "enum":
            needed.update(str(x) for x in schema.get("values", []))
        items = schema.get("items")
        if schema.get("type") == "array" and isinstance(items, dict) and items.get("type") == "enum":
            needed.update(str(x) for x in items.get("values", []))

    out: dict[str, str] = {}
    missing: list[str] = []
    for key in sorted(needed):
        if key in ZH:
            out[key] = ZH[key]
        else:
            missing.append(key)
            out[key] = key.replace("_", " ")

    OUT.write_text(
        yaml.dump({"values": out}, allow_unicode=True, sort_keys=True),
        encoding="utf-8",
    )
    print(f"wrote {len(out)} entries to {OUT}")
    if missing:
        print("fallback (no explicit zh):", ", ".join(missing[:12]), "..." if len(missing) > 12 else "")


if __name__ == "__main__":
    main()
