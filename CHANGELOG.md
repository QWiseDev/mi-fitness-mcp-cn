# Changelog

## Unreleased

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

## 0.2.2（零第三方请求）

- 移除 Web 仪表盘与测试页的 Google Fonts 外链：打开页面不再向 Google 发送任何请求（此前浏览器会上传 IP/UA），改用系统字体栈，国内加载也更快、离线可渲染
- 发往小米的请求覆盖默认 `python-httpx/*` User-Agent 为浏览器 UA，去除脚本指纹（与 Cookie 登录来源一致）
- `docs/PRIVACY.md` 补充浏览器端零外链与最小化出站请求头说明

## 0.2.1（隐私加固）

- 数据安全审计文档 `docs/PRIVACY.md`：全部对外请求清单（仅小米域名）、本机数据存放表、威胁模型与自验方法
- CORS 收紧：默认仅允许本机来源（原来为 `*`，恶意网页可跨站读取本地健康数据）；可用 `MI_FITNESS_CORS_ORIGINS` 覆盖
- Host 头白名单中间件（FastAPI + Flask 双侧）：阻断 DNS 重绑定攻击；非回环绑定时 CLI 自动放行绑定地址，可用 `MI_FITNESS_ALLOWED_HOSTS` 覆盖
- API Key 的 passToken 迁出 SQLite 明文，改存系统 keyring（启动时自动迁移历史数据）；吊销时同步清理
- `api` 命令默认关闭 uvicorn 访问日志（查询参数不再落入终端）
- 新增 `GET /api/export`：本地数据导出为 JSON/CSV（含 Excel BOM），纯离线操作

## 0.2.0

- 内置 Web 仪表盘（`mi-fitness-mcp web`，Flask）：可视化测试全部 API 端点、Key 管理、扫码登录，内置反向代理（自动附加 X-API-Key/X-Admin-Key，上游耗时透传）
- REST API 服务（`mi-fitness-mcp api`，FastAPI）：全部数据端点 + 同步（前台/后台）+ 覆盖统计，交互式文档 `/docs`
- API Key 体系：`POST /api/auth/keys` 用小米凭据换取 `mif_sk_*` Key（类大模型平台风格），支持多账号上下文、last_used 统计、按前缀吊销；静态 Key 经 `MI_FITNESS_API_KEY`、管理端点经 `MI_FITNESS_ADMIN_KEY`
- 扫码登录：逆向小米通用扫码流程（`sid=xiaomiio`），`/api/auth/qr/start|poll` 生成二维码并轮询换取凭据后自动发放 Key，无需浏览器 F12
- Rust 测试页 `testpage/`（可选，内置 Web 仪表盘的 Rust 替代实现）
- 修复：`mcp` 依赖加上界 `<2`（MCP SDK 2.x 移除 `Server.list_tools` 导致启动崩溃）
- 文档：隐私与数据安全审计 `docs/PRIVACY.md`

## 0.1.0

- initial standalone `mi-fitness-mcp` repository
- Xiaomi auth via `userId + passToken`
- Mi Fitness cloud sync for steps, heart rate, calories, body measurements
- MCP tools for sync, summaries, heart rate, body measurements, coverage
