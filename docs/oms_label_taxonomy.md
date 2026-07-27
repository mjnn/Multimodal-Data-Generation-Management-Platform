# OMS 标签树

- **版本**：v2
- **标签数**：68
- **来源**：DMS数据采集标签选择方案_v2.xlsx

## 目录

- [L1 环境与车辆](#L1-环境与车辆)
  - [L1.1 时间维度](#L1.1-时间维度)
  - [L1.2 光照条件](#L1.2-光照条件)
  - [L1.3 天气](#L1.3-天气)
  - [L1.4 温度](#L1.4-温度)
  - [L1.5 噪声](#L1.5-噪声)
  - [L1.6 车辆物理状态](#L1.6-车辆物理状态)
  - [L1.7 车辆运行状态](#L1.7-车辆运行状态)
  - [L1.8 导航与位置](#L1.8-导航与位置)
- [L2 乘员与状态](#L2-乘员与状态)
  - [L2.0 传感器能力](#L2.0-传感器能力)
  - [L2.1 乘员统计与身份](#L2.1-乘员统计与身份)
  - [L2.2 人口属性](#L2.2-人口属性)
  - [L2.3 疲劳](#L2.3-疲劳)
  - [L2.4 健康](#L2.4-健康)
  - [L2.5 情绪](#L2.5-情绪)
  - [L2.6 注意力](#L2.6-注意力)
- [L3 行为交互](#L3-行为交互)
  - [L3.1 语音行为](#L3.1-语音行为)
  - [L3.4 肢体与物品交互](#L3.4-肢体与物品交互)
- [L4 意图推断](#L4-意图推断)
  - [L4.2 隐式意图](#L4.2-隐式意图)
- [L5 决策与反馈](#L5-决策与反馈)
  - [L5.1 决策策略](#L5.1-决策策略)
  - [L5.2 服务执行](#L5.2-服务执行)
  - [L5.3 多模态反馈](#L5.3-多模态反馈)
- [L6 质量与安全](#L6-质量与安全)
  - [L6.1 客观质量指标](#L6.1-客观质量指标)
  - [L6.2 主观体验标签](#L6.2-主观体验标签)
  - [L6.3 安全与合规](#L6.3-安全与合规)
  - [L6.4 长期学习标签](#L6.4-长期学习标签)

---

## L1 环境与车辆 (24 项)

### L1.1 时间维度

| # | ID | 名称 | 类型 | 取值提示 |
|:-:|----|------|------|----------|
| ① | `L1.1.timestamp` | 时间戳 | int64 + string | 合法时间戳 |
| ② | `L1.1.day_period` | 日时段 | enum | dawn/morning/noon/afternoon/dusk/evening/night |
| ③ | `L1.1.commute_flag` | 通勤标记 | enum | morning_commute/evening_commute/non_commute |
| ④ | `L1.1.is_holiday` | 是否节假日 | bool | true/false |

#### `L1.1.timestamp` 时间戳

**定义**：Unix毫秒时间戳 + 时区偏移

**选用理由**：DMS数据帧时间同步基准

**value_schema**：

```json
{
  "type": "composite",
  "fields": [
    {
      "name": "timestamp_ms",
      "type": "int64"
    },
    {
      "name": "timezone",
      "type": "string"
    }
  ],
  "range_hint": "合法时间戳"
}
```

#### `L1.1.day_period` 日时段

**定义**：按小时划分

**选用理由**：不同时段疲劳概率不同

**value_schema**：

```json
{
  "type": "enum",
  "values": [
    "dawn",
    "morning",
    "noon",
    "afternoon",
    "dusk",
    "evening",
    "night"
  ]
}
```

#### `L1.1.commute_flag` 通勤标记

**定义**：基于时间+路线历史判断，工作日早晚高峰期间、目的地为家或公司

**选用理由**：通勤场景疲劳特征不同

**value_schema**：

```json
{
  "type": "enum",
  "values": [
    "morning_commute",
    "evening_commute",
    "non_commute"
  ]
}
```

#### `L1.1.is_holiday` 是否节假日

**定义**：根据日历判断，含周末和法定假日

**选用理由**：节假日驾驶行为模式差异

**value_schema**：

```json
{
  "type": "bool",
  "values": [
    "true",
    "false"
  ]
}
```

### L1.2 光照条件

| # | ID | 名称 | 类型 | 取值提示 |
|:-:|----|------|------|----------|
| ⑤ | `L1.2.dms_face_lux` | DMS面部照度 | float | 0 ~ 50000（弱，中，强） |
| ⑥ | `L1.2.backlight_flag` | 逆光标记 | bool | true/false |
| ⑦ | `L1.2.light_source` | 光源类型 | enum | natural/artificial/mixed |

#### `L1.2.dms_face_lux` DMS面部照度

**定义**：驾驶员面部区域的平均照度（DMS摄像头视野内）

**选用理由**：光照直接影响DMS检测质量

**value_schema**：

```json
{
  "type": "float",
  "range_hint": "0 ~ 50000（弱，中，强）"
}
```

#### `L1.2.backlight_flag` 逆光标记

**定义**：摄像头是否处于逆光状态

**选用理由**：逆光导致面部过曝影响检测

**value_schema**：

```json
{
  "type": "bool",
  "values": [
    "true",
    "false"
  ]
}
```

#### `L1.2.light_source` 光源类型

**定义**：主导光源类别

**选用理由**：光源类型影响红外/可见光切换策略

**value_schema**：

```json
{
  "type": "enum",
  "values": [
    "natural",
    "artificial",
    "mixed"
  ]
}
```

### L1.3 天气

| # | ID | 名称 | 类型 | 取值提示 |
|:-:|----|------|------|----------|
| ⑧ | `L1.3.weather` | 天气类型 | enum | sunny/cloudy/overcast/light_rain/heavy_rain/snow/fog/dust_storm |
| ⑨ | `L1.3.visibility` | 能见度 | int | 0 ~ 5000 m |

#### `L1.3.weather` 天气类型

**定义**：主流天气分类

**选用理由**：天气影响DMS策略与疲劳特征

**value_schema**：

```json
{
  "type": "enum",
  "values": [
    "sunny",
    "cloudy",
    "overcast",
    "light_rain",
    "heavy_rain",
    "snow",
    "fog",
    "dust_storm"
  ]
}
```

#### `L1.3.visibility` 能见度

**定义**：车外摄像头可识别的最远距离估算

**选用理由**：低能见度时驾驶员注意力更集中

**value_schema**：

```json
{
  "type": "int",
  "range_hint": "0 ~ 5000 m"
}
```

### L1.4 温度

| # | ID | 名称 | 类型 | 取值提示 |
|:-:|----|------|------|----------|
| ⑩ | `L1.4.cabin_temp` | 舱内温度 | float | -20 ~ 60 ℃ |
| ⑪ | `L1.4.outside_temp` | 车外温度 | float | -40 ~ 50 ℃ |

#### `L1.4.cabin_temp` 舱内温度

**定义**：车内温度传感器读数（取多个传感器均值）

**选用理由**：高温加速疲劳

**value_schema**：

```json
{
  "type": "float",
  "range_hint": "-20 ~ 60 ℃"
}
```

#### `L1.4.outside_temp` 车外温度

**定义**：车外温度传感器读数

**选用理由**：温差影响舒适度判断

**value_schema**：

```json
{
  "type": "float",
  "range_hint": "-40 ~ 50 ℃"
}
```

### L1.5 噪声

| # | ID | 名称 | 类型 | 取值提示 |
|:-:|----|------|------|----------|
| ⑫ | `L1.5.spl` | 声压级 | float | 30 ~ 120 dB(A) |
| ⑬ | `L1.5.snr_voice` | 语音信噪比 | float | -10 ~ 30 dB |

#### `L1.5.spl` 声压级

**定义**：A计权等效连续声压级 (LAeq)

**选用理由**：高噪声环境影响语音交互DMS

**value_schema**：

```json
{
  "type": "float",
  "range_hint": "30 ~ 120 dB(A)"
}
```

#### `L1.5.snr_voice` 语音信噪比

**定义**：语音信号与背景噪声的功率比

**选用理由**：语音信噪比影响语音指令识别

**value_schema**：

```json
{
  "type": "float",
  "range_hint": "-10 ~ 30 dB"
}
```

### L1.6 车辆物理状态

| # | ID | 名称 | 类型 | 取值提示 |
|:-:|----|------|------|----------|
| ⑭ | `L1.6.seat_occupancy` | 座位占用 | bool[5] | true/false per seat |
| ⑮ | `L1.6.seat_position` | 座椅位置 | float[3] per seat | 各车型标定范围 |
| ⑯ | `L1.6.window_open` | 车窗开度 | float[4] | 0 ~ 100% |
| ⑰ | `L1.6.sunshade_state` | 遮阳帘状态 | bool | true/false |

#### `L1.6.seat_occupancy` 座位占用

**定义**：各座位是否被占用（重量传感器 > 阈值）

**选用理由**：座位占用影响DMS/OMS策略

**value_schema**：

```json
{
  "type": "array",
  "items": {
    "type": "bool"
  },
  "length": 5,
  "range_hint": "true/false per seat"
}
```

#### `L1.6.seat_position` 座椅位置

**定义**：各座椅前后/高低/靠背角度

**选用理由**：座椅位置影响摄像头视角和遮挡

**value_schema**：

```json
{
  "type": "array",
  "items": {
    "type": "float"
  },
  "length": 3,
  "per_seat": true,
  "range_hint": "各车型标定范围"
}
```

#### `L1.6.window_open` 车窗开度

**定义**：各车窗开度百分比

**选用理由**：车窗开度影响光照和噪声

**value_schema**：

```json
{
  "type": "array",
  "items": {
    "type": "float"
  },
  "length": 4,
  "range_hint": "0 ~ 100%"
}
```

#### `L1.6.sunshade_state` 遮阳帘状态

**定义**：遮阳帘打开/关闭

**选用理由**：遮阳帘影响面部光照条件

**value_schema**：

```json
{
  "type": "bool",
  "values": [
    "true",
    "false"
  ]
}
```

### L1.7 车辆运行状态

| # | ID | 名称 | 类型 | 取值提示 |
|:-:|----|------|------|----------|
| ⑱ | `L1.7.speed` | 车速 | float | 0 ~ 250 km/h |
| ⑲ | `L1.7.acceleration` | 加速度 | float[2] | -10 ~ 10 m/s² |
| ⑳ | `L1.7.driving_state` | 行驶状态 | enum | parked/idling/urban_low/urban_high/expressway/traffic_jam/off_road |
| ㉑ | `L1.7.gear` | 档位 | enum | P/R/N/D/M |

#### `L1.7.speed` 车速

**定义**：GPS或CAN车速

**选用理由**：车速影响疲劳阈值设定

**value_schema**：

```json
{
  "type": "float",
  "range_hint": "0 ~ 250 km/h"
}
```

#### `L1.7.acceleration` 加速度

**定义**：纵向/横向加速度

**选用理由**：加速度变化关联注意力状态

**value_schema**：

```json
{
  "type": "array",
  "items": {
    "type": "float"
  },
  "length": 2,
  "range_hint": "-10 ~ 10 m/s²"
}
```

#### `L1.7.driving_state` 行驶状态

**定义**：当前行驶状态分类

**选用理由**：行驶状态决定DMS灵敏度等级

**value_schema**：

```json
{
  "type": "enum",
  "values": [
    "parked",
    "idling",
    "urban_low",
    "urban_high",
    "expressway",
    "traffic_jam",
    "off_road"
  ]
}
```

#### `L1.7.gear` 档位

**定义**：当前档位状态

**选用理由**：档位变化关联注意力转移

**value_schema**：

```json
{
  "type": "enum",
  "values": [
    "P",
    "R",
    "N",
    "D",
    "M"
  ]
}
```

### L1.8 导航与位置

| # | ID | 名称 | 类型 | 取值提示 |
|:-:|----|------|------|----------|
| ㉒ | `L1.8.road_type` | 道路类型 | enum | highway/urban_arterial/local_street/rural/parking_lot/unknown |
| ㉓ | `L1.8.eta_min` | 预计到达时间 | int | 0 ~ 1440 min |
| ㉔ | `L1.8.route_familiarity` | 路线熟悉度 | int | 0 ~ N |

#### `L1.8.road_type` 道路类型

**定义**：当前道路分类

**选用理由**：高速场景需更严格疲劳检测

**value_schema**：

```json
{
  "type": "enum",
  "values": [
    "highway",
    "urban_arterial",
    "local_street",
    "rural",
    "parking_lot",
    "unknown"
  ]
}
```

#### `L1.8.eta_min` 预计到达时间

**定义**：当前预计剩余驾驶时间

**选用理由**：ETA影响驾驶压力评估

**value_schema**：

```json
{
  "type": "int",
  "range_hint": "0 ~ 1440 min"
}
```

#### `L1.8.route_familiarity` 路线熟悉度

**定义**：该路线历史通行次数

**选用理由**：熟悉路线降低警觉性

**value_schema**：

```json
{
  "type": "int",
  "range_hint": "0 ~ N"
}
```

---

## L2 乘员与状态 (19 项)

### L2.0 传感器能力

| # | ID | 名称 | 类型 | 取值提示 |
|:-:|----|------|------|----------|
| ㉕ | `L2.0.dms_available` | DMS可用 | bool | true/false |
| ㉖ | `L2.0.dms_type` | DMS类型 | enum | none/2d_rgb/2d_ir/3d_tof/stereo_ir |

#### `L2.0.dms_available` DMS可用

**定义**：是否配备驾驶员监测摄像头

**选用理由**：DMS功能前置条件

**value_schema**：

```json
{
  "type": "bool",
  "values": [
    "true",
    "false"
  ]
}
```

#### `L2.0.dms_type` DMS类型

**定义**：DMS摄像头类型

**选用理由**：摄像头类型决定检测能力

**value_schema**：

```json
{
  "type": "enum",
  "values": [
    "none",
    "2d_rgb",
    "2d_ir",
    "3d_tof",
    "stereo_ir"
  ]
}
```

### L2.1 乘员统计与身份

| # | ID | 名称 | 类型 | 取值提示 |
|:-:|----|------|------|----------|
| ㉗ | `L2.1.driver_id_hash` | 驾驶员ID | string | 64位hex |
| ㉘ | `L2.1.driver_type` | 驾驶员类型 | enum | registered/guest/unknown |

#### `L2.1.driver_id_hash` 驾驶员ID

**定义**：端侧人脸/声纹哈希值（不可逆脱敏），SHA256后8位

**选用理由**：驾驶员身份关联个性化设置

**value_schema**：

```json
{
  "type": "string",
  "range_hint": "64位hex"
}
```

#### `L2.1.driver_type` 驾驶员类型

**定义**：注册用户/临时访客/未知

**选用理由**：用户类型影响个性化策略

**value_schema**：

```json
{
  "type": "enum",
  "values": [
    "registered",
    "guest",
    "unknown"
  ]
}
```

### L2.2 人口属性

| # | ID | 名称 | 类型 | 取值提示 |
|:-:|----|------|------|----------|
| ㉙ | `L2.2.age_group` | 年龄组 | enum | infant/child/teen/adult/senior |
| ㉚ | `L2.2.role` | 角色 | enum | driver/front_passenger/rear_left/rear_center/rear_right/rear_third |

#### `L2.2.age_group` 年龄组

**定义**：视觉估计年龄区间（非精确年龄，仅分组）

**选用理由**：年龄影响疲劳阈值

**value_schema**：

```json
{
  "type": "enum",
  "values": [
    "infant",
    "child",
    "teen",
    "adult",
    "senior"
  ]
}
```

#### `L2.2.role` 角色

**定义**：座椅位置决定

**选用理由**：识别驾驶员角色

**value_schema**：

```json
{
  "type": "enum",
  "values": [
    "driver",
    "front_passenger",
    "rear_left",
    "rear_center",
    "rear_right",
    "rear_third"
  ]
}
```

### L2.3 疲劳

| # | ID | 名称 | 类型 | 取值提示 |
|:-:|----|------|------|----------|
| ㉛ | `L2.3.fatigue_level` | 疲劳等级 | enum | alert/mild_fatigue/moderate_fatigue/severe_fatigue |
| ㉜ | `L2.3.perclos` | PERCLOS值 | float | 0 ~ 1.0 |
| ㉝ | `L2.3.yawn_count` | 打哈欠次数 | int | 0 ~ N |
| ㉞ | `L2.3.blink_rate` | 眨眼频率 | float | 0 ~ 60 bpm |
| ㉟ | `L2.3.head_nodding` | 点头频率 | float | 0 ~ 30 次/min |

#### `L2.3.fatigue_level` 疲劳等级

**定义**：综合疲劳评估等级

**选用理由**：DMS核心输出：疲劳等级

**value_schema**：

```json
{
  "type": "enum",
  "values": [
    "alert",
    "mild_fatigue",
    "moderate_fatigue",
    "severe_fatigue"
  ]
}
```

#### `L2.3.perclos` PERCLOS值

**定义**：单位时间内眼睛闭合时间占比

**选用理由**：疲劳检测核心指标

**value_schema**：

```json
{
  "type": "float",
  "range_hint": "0 ~ 1.0"
}
```

#### `L2.3.yawn_count` 打哈欠次数

**定义**：最近5分钟内打哈欠次数

**选用理由**：疲劳辅助指标

**value_schema**：

```json
{
  "type": "int",
  "range_hint": "0 ~ N"
}
```

#### `L2.3.blink_rate` 眨眼频率

**定义**：每分钟眨眼次数

**选用理由**：疲劳辅助指标

**value_schema**：

```json
{
  "type": "float",
  "range_hint": "0 ~ 60 bpm"
}
```

#### `L2.3.head_nodding` 点头频率

**定义**：头部周期性下垂频率（微睡眠标志）

**选用理由**：微睡眠检测指标

**value_schema**：

```json
{
  "type": "float",
  "range_hint": "0 ~ 30 次/min"
}
```

### L2.4 健康

| # | ID | 名称 | 类型 | 取值提示 |
|:-:|----|------|------|----------|
| ㊱ | `L2.4.heart_rate` | 心率 | int | 40 ~ 200 bpm |
| ㊲ | `L2.4.resp_rate` | 呼吸频率 | int | 8 ~ 40 bpm |

#### `L2.4.heart_rate` 心率

**定义**：毫米波雷达/穿戴设备心率估计值

**选用理由**：心率异常关联疲劳/健康状态

**value_schema**：

```json
{
  "type": "int",
  "range_hint": "40 ~ 200 bpm"
}
```

#### `L2.4.resp_rate` 呼吸频率

**定义**：毫米波雷达呼吸频率估计值

**选用理由**：呼吸频率关联疲劳状态

**value_schema**：

```json
{
  "type": "int",
  "range_hint": "8 ~ 40 bpm"
}
```

### L2.5 情绪

| # | ID | 名称 | 类型 | 取值提示 |
|:-:|----|------|------|----------|
| ㊳ | `L2.5.facial_expression` | 面部表情 | enum[] | smile/laugh/frown/brow_furrow/lip_press/eye_wide/mouth_open/neutral |
| ㊴ | `L2.5.emotion_category` | 情绪分类 | enum | neutral/happy/sad/angry/surprised/fearful/disgusted/unknown |

#### `L2.5.facial_expression` 面部表情

**定义**：可观察的面部肌肉动作

**选用理由**：面部表情关联情绪状态

**value_schema**：

```json
{
  "type": "array",
  "items": {
    "type": "enum",
    "values": [
      "smile",
      "laugh",
      "frown",
      "brow_furrow",
      "lip_press",
      "eye_wide",
      "mouth_open",
      "neutral"
    ]
  }
}
```

#### `L2.5.emotion_category` 情绪分类

**定义**：谨慎使用。仅当面部+声音+情境三者一致且置信度>0.8时输出

**选用理由**：情绪影响交互策略

**value_schema**：

```json
{
  "type": "enum",
  "values": [
    "neutral",
    "happy",
    "sad",
    "angry",
    "surprised",
    "fearful",
    "disgusted",
    "unknown"
  ]
}
```

### L2.6 注意力

| # | ID | 名称 | 类型 | 取值提示 |
|:-:|----|------|------|----------|
| ㊵ | `L2.6.gaze_target` | 注视目标 | enum | road_ahead/left_mirror/right_mirror/rear_mirror/instrument_cluster/center_screen/left_window/right_window/passenger/phone/other |
| ㊶ | `L2.6.gaze_duration` | 注视时长 | float | 0 ~ N s |
| ㊷ | `L2.6.distraction_level` | 分心等级 | enum | attentive/slight_distraction/moderate_distraction/severe_distraction |
| ㊸ | `L2.6.distraction_type` | 分心类型 | enum | phone_use/eating_drinking/infotainment/adjusting_controls/passenger_interaction/child_care/external_event/other |

#### `L2.6.gaze_target` 注视目标

**定义**：驾驶员当前注视的对象分类

**选用理由**：DMS核心：视线追踪

**value_schema**：

```json
{
  "type": "enum",
  "values": [
    "road_ahead",
    "left_mirror",
    "right_mirror",
    "rear_mirror",
    "instrument_cluster",
    "center_screen",
    "left_window",
    "right_window",
    "passenger",
    "phone",
    "other"
  ]
}
```

#### `L2.6.gaze_duration` 注视时长

**定义**：对当前目标的持续注视时长

**选用理由**：注视时长判断注意力

**value_schema**：

```json
{
  "type": "float",
  "range_hint": "0 ~ N s"
}
```

#### `L2.6.distraction_level` 分心等级

**定义**：视线离开道路的累计时长占比（30s窗口）

**选用理由**：DMS核心输出：分心等级

**value_schema**：

```json
{
  "type": "enum",
  "values": [
    "attentive",
    "slight_distraction",
    "moderate_distraction",
    "severe_distraction"
  ]
}
```

#### `L2.6.distraction_type` 分心类型

**定义**：分心行为的分类

**选用理由**：分心类型分类

**value_schema**：

```json
{
  "type": "enum",
  "values": [
    "phone_use",
    "eating_drinking",
    "infotainment",
    "adjusting_controls",
    "passenger_interaction",
    "child_care",
    "external_event",
    "other"
  ]
}
```

---

## L3 行为交互 (5 项)

### L3.1 语音行为

| # | ID | 名称 | 类型 | 取值提示 |
|:-:|----|------|------|----------|
| ㊹ | `L3.1.dialogue_type` | 对话类型 | enum | hmi_command/casual_chat_with_hmi/human_to_human/phone_call/solo_talking_to_self/singing/humming/silence |
| ㊺ | `L3.1.paralinguistic` | 副语言事件 | enum[] | laugh/sigh/cough/sneeze/cry/yawn_sound/groan/clear_throat |

#### `L3.1.dialogue_type` 对话类型

**定义**：当前语音交互的分类

**选用理由**：语音行为类型分析

**value_schema**：

```json
{
  "type": "enum",
  "values": [
    "hmi_command",
    "casual_chat_with_hmi",
    "human_to_human",
    "phone_call",
    "solo_talking_to_self",
    "singing",
    "humming",
    "silence"
  ]
}
```

#### `L3.1.paralinguistic` 副语言事件

**定义**：非词汇语音事件

**选用理由**：打哈欠/叹气等关联疲劳

**value_schema**：

```json
{
  "type": "array",
  "items": {
    "type": "enum",
    "values": [
      "laugh",
      "sigh",
      "cough",
      "sneeze",
      "cry",
      "yawn_sound",
      "groan",
      "clear_throat"
    ]
  }
}
```

### L3.4 肢体与物品交互

| # | ID | 名称 | 类型 | 取值提示 |
|:-:|----|------|------|----------|
| ㊻ | `L3.4.body_action` | 肢体动作 | enum | driving/eating/drinking/smoking/phone_calling/phone_using/reading/makeup/adjusting_clothing/buckling_seatbelt/holding_child/petting/resting_sleeping/other/none |
| ㊼ | `L3.4.object_in_hand` | 手中物品 | enum | phone/food/beverage/cigarette/book/newspaper/makeup/toy/tissue/child/pet/other/none |
| ㊽ | `L3.4.dangerous_action` | 危险行为标记 | bool | true/false |

#### `L3.4.body_action` 肢体动作

**定义**：乘员当前的身体动作分类

**选用理由**：DMS核心：肢体动作检测

**value_schema**：

```json
{
  "type": "enum",
  "values": [
    "driving",
    "eating",
    "drinking",
    "smoking",
    "phone_calling",
    "phone_using",
    "reading",
    "makeup",
    "adjusting_clothing",
    "buckling_seatbelt",
    "holding_child",
    "petting",
    "resting_sleeping",
    "other",
    "none"
  ]
}
```

#### `L3.4.object_in_hand` 手中物品

**定义**：乘员手中持有的物品分类

**选用理由**：手中物品检测

**value_schema**：

```json
{
  "type": "enum",
  "values": [
    "phone",
    "food",
    "beverage",
    "cigarette",
    "book",
    "newspaper",
    "makeup",
    "toy",
    "tissue",
    "child",
    "pet",
    "other",
    "none"
  ]
}
```

#### `L3.4.dangerous_action` 危险行为标记

**定义**：是否检测到危险行为（如驾驶中双手离开方向盘操作手机）

**选用理由**：DMS核心：危险行为检测

**value_schema**：

```json
{
  "type": "bool",
  "values": [
    "true",
    "false"
  ]
}
```

---

## L4 意图推断 (2 项)

### L4.2 隐式意图

| # | ID | 名称 | 类型 | 取值提示 |
|:-:|----|------|------|----------|
| ㊾ | `L4.2.physiology_intent` | 生理推断意图 | enum + rationale | 枚举值 + 依据句子 |
| ㊿ | `L4.2.implicit_confidence` | 隐式意图置信度 | float | 0 ~ 1 |

#### `L4.2.physiology_intent` 生理推断意图

**定义**：基于生理状态推断的需求

**选用理由**：疲劳时推断休息需求

**value_schema**：

```json
{
  "type": "composite",
  "fields": [
    {
      "name": "value",
      "type": "enum"
    },
    {
      "name": "rationale",
      "type": "string"
    }
  ],
  "range_hint": "枚举值 + 依据句子"
}
```

#### `L4.2.implicit_confidence` 隐式意图置信度

**定义**：该隐式意图判断的置信度

**选用理由**：推断结果可信度

**value_schema**：

```json
{
  "type": "float",
  "range_hint": "0 ~ 1"
}
```

---

## L5 决策与反馈 (8 项)

### L5.1 决策策略

| # | ID | 名称 | 类型 | 取值提示 |
|:-:|----|------|------|----------|
| 51 | `L5.1.response_strategy` | 响应策略 | enum | execute_directly/ask_confirm/proactive_push/silent_execute/deferred/rejected |
| 52 | `L5.1.trigger_source` | 触发来源 | enum | user_command/system_proactive/condition_trigger/scheduled |
| 53 | `L5.1.decision_confidence` | 决策置信度 | float | 0 ~ 1 |

#### `L5.1.response_strategy` 响应策略

**定义**：系统对用户意图的响应方式

**选用理由**：DMS警告策略

**value_schema**：

```json
{
  "type": "enum",
  "values": [
    "execute_directly",
    "ask_confirm",
    "proactive_push",
    "silent_execute",
    "deferred",
    "rejected"
  ]
}
```

#### `L5.1.trigger_source` 触发来源

**定义**：服务触发方式

**选用理由**：DMS触发方式

**value_schema**：

```json
{
  "type": "enum",
  "values": [
    "user_command",
    "system_proactive",
    "condition_trigger",
    "scheduled"
  ]
}
```

#### `L5.1.decision_confidence` 决策置信度

**定义**：模型输出的决策置信度

**选用理由**：决策可信度

**value_schema**：

```json
{
  "type": "float",
  "range_hint": "0 ~ 1"
}
```

### L5.2 服务执行

| # | ID | 名称 | 类型 | 取值提示 |
|:-:|----|------|------|----------|
| 54 | `L5.2.action` | 执行动作 | enum | 见动作枚举 |
| 55 | `L5.2.result` | 执行结果 | enum | success/failed/partial_success/timeout |

#### `L5.2.action` 执行动作

**定义**：系统执行的具体动作

**选用理由**：DMS警告执行动作

**value_schema**：

```json
{
  "type": "enum",
  "values": [
    "见动作枚举"
  ]
}
```

#### `L5.2.result` 执行结果

**定义**：动作执行结果分类

**选用理由**：执行结果追踪

**value_schema**：

```json
{
  "type": "enum",
  "values": [
    "success",
    "failed",
    "partial_success",
    "timeout"
  ]
}
```

### L5.3 多模态反馈

| # | ID | 名称 | 类型 | 取值提示 |
|:-:|----|------|------|----------|
| 56 | `L5.3.tts_text` | TTS播报文本 | string | 文本 |
| 57 | `L5.3.haptic_type` | 触觉反馈类型 | enum | none/seat_vibration/steering_vibration/both |
| 58 | `L5.3.screen_content` | 屏幕显示内容 | enum | nav_map/nav_instruction/music_player/phone_ui/settings/climate_ui/notification/toast/other |

#### `L5.3.tts_text` TTS播报文本

**定义**：系统播报的完整文本

**选用理由**：DMS语音警告内容

**value_schema**：

```json
{
  "type": "string",
  "range_hint": "文本"
}
```

#### `L5.3.haptic_type` 触觉反馈类型

**定义**：触觉反馈的类型

**选用理由**：DMS触觉警告方式

**value_schema**：

```json
{
  "type": "enum",
  "values": [
    "none",
    "seat_vibration",
    "steering_vibration",
    "both"
  ]
}
```

#### `L5.3.screen_content` 屏幕显示内容

**定义**：中控屏显示的页面/弹窗类型

**选用理由**：DMS视觉警告内容

**value_schema**：

```json
{
  "type": "enum",
  "values": [
    "nav_map",
    "nav_instruction",
    "music_player",
    "phone_ui",
    "settings",
    "climate_ui",
    "notification",
    "toast",
    "other"
  ]
}
```

---

## L6 质量与安全 (10 项)

### L6.1 客观质量指标

| # | ID | 名称 | 类型 | 取值提示 |
|:-:|----|------|------|----------|
| 59 | `L6.1.e2e_latency` | 端到端延迟分布 | float[3] | 0 ~ N ms |
| 60 | `L6.1.task_completion_rate` | 任务完成率 | float | 0 ~ 1 |

#### `L6.1.e2e_latency` 端到端延迟分布

**定义**：从用户说完到系统完成动作的延迟(P50/P95/P99)

**选用理由**：DMS响应延迟评估

**value_schema**：

```json
{
  "type": "array",
  "items": {
    "type": "float"
  },
  "length": 3,
  "range_hint": "0 ~ N ms"
}
```

#### `L6.1.task_completion_rate` 任务完成率

**定义**：用户发起的任务中成功完成的比例

**选用理由**：DMS任务完成率

**value_schema**：

```json
{
  "type": "float",
  "range_hint": "0 ~ 1"
}
```

### L6.2 主观体验标签

| # | ID | 名称 | 类型 | 取值提示 |
|:-:|----|------|------|----------|
| 61 | `L6.2.explicit_rating` | 显式评分 | int | 1 ~ 5 |
| 62 | `L6.2.manual_correction` | 是否手动纠正 | bool | true/false |

#### `L6.2.explicit_rating` 显式评分

**定义**：用户主动给出的评分

**选用理由**：DMS功能满意度

**value_schema**：

```json
{
  "type": "int",
  "range_hint": "1 ~ 5"
}
```

#### `L6.2.manual_correction` 是否手动纠正

**定义**：用户是否在系统自动执行后手动纠正了结果

**选用理由**：DMS误报反馈

**value_schema**：

```json
{
  "type": "bool",
  "values": [
    "true",
    "false"
  ]
}
```

### L6.3 安全与合规

| # | ID | 名称 | 类型 | 取值提示 |
|:-:|----|------|------|----------|
| 63 | `L6.3.distraction_warning_count` | 分心警告次数 | int | 0 ~ N |
| 64 | `L6.3.fatigue_warning_count` | 疲劳警告次数 | int | 0 ~ N |
| 65 | `L6.3.dangerous_behavior` | 危险行为检测 | list of enum | phone_while_driving/eating_while_driving/no_hands/no_seatbelt/other |
| 66 | `L6.3.takeover_event` | 交互接管事件 | int | 0 ~ N |

#### `L6.3.distraction_warning_count` 分心警告次数

**定义**：系统触发的分心驾驶警告总次数

**选用理由**：DMS分心警告统计

**value_schema**：

```json
{
  "type": "int",
  "range_hint": "0 ~ N"
}
```

#### `L6.3.fatigue_warning_count` 疲劳警告次数

**定义**：系统触发的疲劳驾驶警告总次数

**选用理由**：DMS疲劳警告统计

**value_schema**：

```json
{
  "type": "int",
  "range_hint": "0 ~ N"
}
```

#### `L6.3.dangerous_behavior` 危险行为检测

**定义**：检测到的危险行为列表

**选用理由**：DMS危险行为记录

**value_schema**：

```json
{
  "type": "array",
  "items": {
    "type": "enum",
    "values": [
      "phone_while_driving",
      "eating_while_driving",
      "no_hands",
      "no_seatbelt",
      "other"
    ]
  }
}
```

#### `L6.3.takeover_event` 交互接管事件

**定义**：因语音/触控交互导致驾驶员注意力分散、需要接管的事件

**选用理由**：DMS安全事件记录

**value_schema**：

```json
{
  "type": "int",
  "range_hint": "0 ~ N"
}
```

### L6.4 长期学习标签

| # | ID | 名称 | 类型 | 取值提示 |
|:-:|----|------|------|----------|
| 67 | `L6.4.personalization_gain` | 个性化增益 | float | -1 ~ 1 |
| 68 | `L6.4.ab_experiment_group` | A/B实验分组 | string | 分组ID |

#### `L6.4.personalization_gain` 个性化增益

**定义**：个性化模型 vs 通用模型的效果差异

**选用理由**：DMS个性化效果评估

**value_schema**：

```json
{
  "type": "float",
  "range_hint": "-1 ~ 1"
}
```

#### `L6.4.ab_experiment_group` A/B实验分组

**定义**：当前用户所属的实验分组

**选用理由**：DMS算法实验

**value_schema**：

```json
{
  "type": "string",
  "range_hint": "分组ID"
}
```

---

> 由 `scripts/generate_oms_taxonomy_html.py` 从 `config/oms_label_taxonomy.yaml` 自动生成。
