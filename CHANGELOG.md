# Changelog

## Unreleased

- 修复（吸收上游 v0.3.0 安全修复）：**按前缀吊销 Key 的误伤漏洞**——`mif_` 这类短前缀会一次吊销全部 Key；现在要求前缀至少 12 位且唯一匹配（多匹配返回 409），响应改为脱敏展示。密钥比较（静态 Key / Admin Key）改用 `hmac.compare_digest` 恒定时间比较，防时序侧信道。扫码确认后重复轮询 QR 接口不再反复返回完整 API Key（只在确认那一次返回）。仪表盘 Key 列表的标签/User ID/前缀进入 innerHTML 前统一 HTML 转义，阻断存储型 XSS
- 修复：睡眠按**起床日**归属（吸收上游 v0.4.0）——0:08 入睡与 23:21 入睡的两晚此前按入睡日会落在同一天造成假峰值；现逐晚行与 `sleep_minutes` 序列统一按起床日归属
- 性能：SQLite 启用 WAL 日志模式（持久化），写不再阻塞读
- 新增：**每日活力值（活力值/成就域）**——经真实账号探测确认 `vitality` 是 `get_fitness_data_by_time` 的合法数据 key（与 steps/sleep 同一管线，无需专有接口；`vitality/get_achievement_data` 专有端点因 App 装有腾讯 Legu 壳、参数在运行时解密代码中无法静态获取而放弃）。新增 `VitalityRecord` 模型 + `vitality_records` 表（按 user_id+date upsert）+ 适配器 `iter_vitality` + 同步类型 `vitality`（REST/增量同步均已纳入）+ REST `GET /api/vitality` + MCP 工具 `query_vitality`（第 21 个）；`get_health_report` 的逐日行/合计/均值新增 `vitality` 字段
- 新增：**运动游标真增量**——适配器 `fetch_sport_records_by_watermark`（分页拉取 watermark 之后的变更记录，游标不前进时自动终止）+ `POST /api/workouts/sync-incremental?watermark=N`（只拉变更并 upsert，响应携带新游标供调用方持久化；首次不传即全量刷新，幂等）；运动解析重构为 `_workout_from_item` 供两条路径共用
- 新增：`get_latest_data` 与 `GET /api/latest` 附带**本地全类型数据新鲜度**——8 种数据类型各自的最新记录时间，时间戳类型带 `age_hours`，agent 可一次判断"哪个类型的数据旧了需要先同步"
- 新增：**睡眠官方字段全量入库**——`sleep_sessions` 表新增 13 列（`sleep_efficiency` 官方睡眠效率、`awake_count` 清醒次数、`avg/max/min_hr` 心率、`avg/max/min_spo2` 血氧、`avg_breath` 呼吸率、`avg/max/min_hrv` 心率变异性、`raw_payload` 云端完整 payload JSON 含 HRV 分位与算法版本等全部字段），既有库打开时自动 ALTER 迁移；适配器/模型/查询/睡眠分析全链路透出，分析逐晚行与汇总的效率优先采用云端官方值、缺失时回退计算值
- 修复：**云端一夜睡眠被拆成多条重叠碎片记录**（App 端 sleep_segment 表同样分片，实测 22:54-06:43 主夜附带 22:54-23:19 与 00:11-01:44 两段碎片），此前每条碎片都被当作独立夜晚入库，30 天数出 54 晚且时长被碎片稀释。适配器现按时间重叠分组合并，每组保留覆盖最宽的代表记录
- 修复：睡眠时间语义——云端 `duration` 是实际入睡分钟（deep+light+rem），`sleep_awake_duration` 是清醒分钟，两者相加即卧床时长；此前把 `time_asleep` 错算成 `duration - awake`（重复扣减），睡眠效率虚高失真。`time_asleep` 现等于入睡分钟，分析效率改为 入睡/(入睡+清醒)
- 新增：小睡标记——云端不带 is_nap，适配器按本地开始时间（08:00-19:59）启发式标记，`query_sleep` 的 `include_naps=false` 过滤随之生效
- 修复：**睡眠分期映射整体错误**——云端 `items[].state` 真实编码为 2=deep / 3=light / 4=rem / 5=awake（由真实账号 items 分段直方图与顶层 `sleep_deep/light/rem/awake_duration` 聚合逐夜对账得出，字段名与 APK 内一致）；此前映射为猜测值，把深睡错标成浅睡、REM 与清醒互换，导致库里从无 deep 记录且 time_asleep 虚高。同时修正清醒时长字段名（`awake_duration` → `sleep_awake_duration`）。受影响的历史睡眠数据需用 `force_full_sync` 重拉 sleep
- 修复：`get_sleep_analysis` 分期分钟数对同一分期多段数据只保留最后一段（dict 推导覆盖）而非累加，深/浅/REM 占比失真
- 新增：三个本地聚合分析工具（MCP + REST，纯 SQLite 不触云）：`query_sleep_analysis`（`/api/sleep-analysis`，逐晚时长/效率/评分 + 深浅 REM 分期、入睡/起床均值含跨午夜折算、工作日 vs 周末、前后半程趋势、小睡合计）；`compare_periods`（`/api/compare-periods`，两区间 health report 对比，仅对平均值算差值）；`detect_anomalies`（`/api/anomalies`，窗口末段 vs 基线：静息心率 +5bpm / 血氧 -2pct / 压力 +10 / 睡眠 -45min 或 -15%，基线与近期数据不足时不误报）
- 新增：云端 watermark 增量能力（来自 APK 静态分析发现的未用端点）：适配器 `get_max_watermark` / `get_latest_sport_record`；REST `GET /api/latest`（云端游标 + 最新运动含 value 摘要）与 `GET /api/cloud-watermark`；MCP 工具 `get_latest_data`（第 17 个）——游标未变化即代表所有数据域无新记录
- 新增：每小时增量同步接入 watermark 短路——云端游标与上次成功拉取一致且距上次全量不足 6 小时时直接跳过本轮（游标获取失败仍照常全量，最坏 6 小时全量一次），把定时任务从"每小时重查 3 天"降为"每小时 1 次游标探测"
- 新增：`get_workout_detail`（MCP 工具 + REST `/api/workouts/{workout_id}/detail`）：云端运动记录内嵌的 `value` 摘要（训练效果、心率区间时长、训练负荷、恢复时间等 App 详情页数据）+ 本地运动窗口内心率样本曲线；适配器离线或云端无该记录时仍返回本地数据。GPS 轨迹/分段需未公开的云端详情接口，暂不包含
- 新增：`query_metric_series` 支持健康指标序列——`weight_kg`（当日最后一次测量，此前枚举存在但永远返回空）、`sleep_minutes`（按会话开始日期求和）、`resting_heart_rate` / `spo2_pct` / `stress_score`（当日均值），周/月聚合照常可用；REST `/api/metric-series` 同步扩展
- 新增：`get_health_report`（MCP 工具 + REST `/api/health-report`）：一次调用返回日期范围内逐日步数/卡路里/睡眠/静息心率/血氧/压力及区间合计与均值，替代 agent 多次查询拼接
- 修复：网页仪表盘读取 REST 实际字段（`active_kcal`、`distance_m`、`spo2_pct`、`stress_score`、睡眠 `stages[]`）并解包 `data` 信封；概览卡片取窗口内最新样本；血氧缺失时显示 `--`；HTTP 错误不再向调用方返回看似成功的载荷；同步部分完成/失败时如实提示
- 修复：Web 代理仅在浏览器未提供 `X-API-Key` 时附加服务器静态 Key，避免覆盖扫码登录账号的账号 Key
- 新增：`deploy/` 服务器部署脚本（systemd 单元、每小时增量同步、全历史一次性回填、只读 keyring 后端）；全历史脚本等待忙碌 API 重试加上限，避免无人值守时卡死

## 0.4.0（仪表盘重做 + 数据模型修复）

**重做**

- Web 仪表盘从零重写：无 emoji、无第三方字体、无框架，纯 ES Module + CSS 变量；响应式（桌面左导航栏 → 平板窄栏 → 手机底部标签栏），暗色/亮色跟随系统
- 新增「洞察」页：区间报告（对比上一周期）、个人纪录、心率区间分布、数据缺口
- 趋势页支持 14 个指标按日/周/月聚合
- 仪表盘代理增加严格 CSP、X-Frame-Options、Referrer-Policy，JS 模板自动转义防 XSS

**修复**

- 睡眠按入睡日归属时，0:08 入睡与 23:21 入睡的两晚落在同一天，睡眠序列出现翻倍的假峰值；改为按起床日归属
- 总览页睡眠分期条无法显示（flex 布局嵌套 grid）
- 图表 X 轴最后一个标签与相邻标签重叠
- 图表悬浮数据放在 HTML 属性里，改回内存对象

**测试**：115 → 132 个，新增前端专项（无 emoji、CSP 兼容、XSS 转义、静态资源可访问）

## 0.3.0（分析与可靠性）

**新增**

- 演示模式：`--demo` / `MI_FITNESS_DEMO=1` 用合成数据体验全部功能，无需小米账号；写入独立的 `demo.db`
- `dashboard` 命令：一条命令同时启动 API 与仪表盘并打开浏览器
- 命令行：`status` `overview` `report` `records` `gaps` `export`，均不联网，支持 `--json`；`sync` 增加 `--full`、`-v` 进度；全局 `--version`
- 6 个分析型 MCP 工具与对应 REST 端点：`get_health_overview` `get_period_report`（自动对比上一等长区间）`get_sleep_summary`（入睡时间波动、各阶段占比）`get_heart_rate_summary`（心率区间）`get_personal_records`（含连续达标）`find_data_gaps`
- `query_metric_series` 指标从 3 个扩到 14 个：睡眠/运动时长、静息/平均/最高心率、血氧、压力、体重、BMI、体脂
- 仪表盘新增「健康洞察」页（区间报告、个人纪录、数据缺口）；指标页覆盖全部指标
- 数据库权限：新建时收紧为 0600（类 Unix）

**修复**

- 同日增量同步崩溃：游标落在今天时，起点（带时刻）晚于终点（当天零点），抛 `start_date must not be after end_date`。现在从游标所在日重拉，UPSERT 保证不重复
- 同步统计失真：`updated` 恒为 0（UPSERT 的 rowcount 总是 1），现在如实区分新增 / 更新 / 未变
- 游标可能越过未入库的数据：改为每个分块整体入库成功后才推进，且只前进不后退（补拉历史不再把增量起点拉回去）
- 多账号互相覆盖：记录 ID 不含账号，两个账号同日数据会共用一行，后者覆盖前者；主键改为 `(user_id, id)`，同步游标改为按账号。**旧库启动时自动迁移，数据不丢**
- `aggregation=latest` 被静默当成求和；`weight_kg` 在 MCP 枚举里却始终返回空
- 仪表盘概览卡片全是 `--`：前端读取的字段名与 API 实际返回不符；睡眠分期条同理
- 仪表盘 API Key 列表无法吊销（读取了不存在的字段），且标签、用户 ID 未转义（存储型 XSS）
- 按前缀吊销 Key 时 `mif_` 这样的短前缀会吊销全部 Key；现在要求至少 12 位且唯一匹配
- 扫码确认后重复轮询会反复返回完整 API Key；现在只在确认那一次返回

**性能与结构**

- 写入改为单事务批量 UPSERT，并启用 WAL：一天的逐分钟心率（1440 条）从约 12 秒降到约 20 毫秒
- 日期过滤改用时间列的范围比较，走 `(user_id, 时间)` 索引，不再对每行 `substr`
- 心率统计在 SQL 里聚合，不再把几万条样本读进内存
- 8 张表的 DDL、写入、过滤、覆盖统计由一份声明式定义生成，存储层从 878 行降到 559 行
- MCP 服务改为装饰器注册工具，schema 与处理函数同处定义；MCP 与 REST 共用同一个 `sync_many`
- 数据类型清单只在 `models.DATA_TYPES` 定义一份
- 密钥比较改用 `hmac.compare_digest`（恒定时间）
- 多设备同日记录取各指标最大值而非相加（预防性处理：当前云端适配器不写 `device_id`，尚不会触发）
- 签名 nonce 的时间戳改用 `time.time()`（结果不变，仅去掉对本地时区函数的依赖）
- 删除未使用的模型、配置项与重复的前端目录 `testpage/`（与 `web_assets/` 逐字节相同）；探测脚本移入 `tools/`

**测试**：28 → 115 个，覆盖迁移、同步游标、分析、API 鉴权、CLI 与 MCP 工具注册
