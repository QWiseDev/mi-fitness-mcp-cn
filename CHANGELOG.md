# Changelog

## Unreleased

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
