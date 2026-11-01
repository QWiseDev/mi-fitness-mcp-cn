# <服务器IP> 部署说明

上游仓库：https://github.com/HUAYUE1024/mi-fitness-mcp-cn

上游提交：`1767b4921ad94e38a68ac77cbb0bdf809a92864d`，版本 `0.2.2`。

本地部署补丁：

- Web 代理只在浏览器未提供 `X-API-Key` 时附加服务器静态 Key，避免覆盖扫码登录得到的账号 Key。对应回归用例为 `test_proxy_preserves_client_api_key`。
- 网页从 REST 响应的 `data` 数组读取记录，使用实际的距离、卡路里、血氧、压力和睡眠分期字段；同步失败或部分完成时不再提示全部成功。前端回归命令为 `node --test tests/test_dashboard.mjs`，不需要安装 npm 依赖。

## 服务器位置

| 内容 | 路径 |
|---|---|
| 源码 | `/opt/mi-fitness-mcp-cn/app` |
| Python 虚拟环境 | `/opt/mi-fitness-mcp-cn/.venv` |
| 持久化数据 | `/var/lib/mi-fitness-mcp` |
| 配置 | `/var/lib/mi-fitness-mcp/config/mi-fitness-mcp/config.json` |
| SQLite | `/var/lib/mi-fitness-mcp/data/mi-fitness-mcp/mi_fitness.db` |
| 运行环境和密钥 | `/etc/mi-fitness-mcp/runtime.env`，仅 root 可读 |
| 服务用户 | `mifitness` |

API 监听 `127.0.0.1:8321`，Web 监听 `127.0.0.1:8322`。两个 systemd 服务开机自启，异常退出后重启。Web 使用 Gunicorn，保持上游应用代码与网页资源结构。

服务器没有配置系统 keyring，API 按上游逻辑降级将小米 passToken 存入 SQLite。数据目录为 `0700`，服务进程 `UMask=0077`。备份数据库时必须按凭据文件保护；恢复时同时保留运行环境文件。

## 访问与使用

在个人电脑建立 SSH 隧道：

```bash
ssh -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 \
  -L 8321:127.0.0.1:8321 \
  -L 8322:127.0.0.1:8322 \
  root@<服务器IP>
```

浏览器访问 `http://127.0.0.1:8322/`，扫码登录后点击同步。账号 Key 保存在当前浏览器的 localStorage；更换浏览器时需重新输入已保存的 Key 或重新扫码。页面默认日期为昨天至今天；查看历史记录时需扩大日期范围。网页脚本更新后可用 `Cmd+Shift+R` 强制刷新。

CLI/MCP 的默认账号与网页扫码账号分开管理。8321 是 REST API，不是 HTTP MCP 地址。服务器 Hermes 已通过下述独立 MCP 配置绑定现有扫码账号。

## Hermes MCP 接入

2026-10-18 已将 `mi-fitness` 接入同服务器上的 Hermes 消息网关和 Web 界面，两者配置文件分别为：

- 网关及 CLI：`/root/.hermes/config.yaml`。
- Web 界面：`/etc/hermes-webui-config.yaml`，由 `HERMES_CONFIG_PATH` 指定。

两份配置均仅追加 `mcp_servers.mi-fitness`，原配置备份在 `/root/.hermes/backups/*before-mi-fitness-*.yaml`，权限为 `0600`。MCP 使用原生 stdio 协议，通过 `runuser -u mifitness` 运行，独立配置位于 `/var/lib/mi-fitness-mcp/mcp-config/mi-fitness-mcp/config.json`，与 Web/API 共用原 SQLite 数据库。

`deploy/mi_fitness_keyring.py` 提供只读 keyring 后端，从数据库读取唯一有效扫码账号的凭据；不在 Hermes 配置中复制凭据，不添加系统依赖，也不更改 API 的默认账号配置。账号出现歧义时拒绝读取。对应 MCP 环境变量为：

```yaml
XDG_CONFIG_HOME: /var/lib/mi-fitness-mcp/mcp-config
PYTHONPATH: /opt/mi-fitness-mcp-cn/app/deploy
PYTHON_KEYRING_BACKEND: mi_fitness_keyring.SQLiteKeyring
```

已验证原生 MCP 握手及云端连接，Hermes 客户端可读取历史数据；CLI、飞书和 Telegram 工具选择均包含 14 个工具。Web 界面 MCP 列表显示已连接、14 个工具全部 active。消息网关通过 `SIGUSR1` 优雅重载，并确认其 Mi Fitness MCP 子进程以 `mifitness` 用户运行。

在 Hermes 新建会话后，可直接要求“查询最近 7 天步数”“分析最近一个月的睡眠”或“检查运动健康数据覆盖范围”。工具名以 `mcp__mi_fitness__` 开头。已有会话若未出现新工具，可使用 `/reload-mcp` 或新建会话。

## 运维

```bash
ssh root@<服务器IP> 'systemctl status mi-fitness-api mi-fitness-web --no-pager'
ssh root@<服务器IP> 'journalctl -u mi-fitness-api -u mi-fitness-web -n 80 --no-pager'
ssh root@<服务器IP> 'systemctl restart mi-fitness-api mi-fitness-web'
```

后续更新需保留本地补丁并重新运行测试。不要用未带补丁的上游文件直接覆盖 `web.py`。上游没有内置定时调度；本服务器使用下述 systemd timer 自动增量同步。

## 每小时增量同步

`mi-fitness-sync.timer` 按北京时间每小时整点触发 `mi-fitness-sync.service`，调度精度为 1 分钟，开机自动启用。`Persistent=true` 会在停机后补触发一次；脚本从已保存的成功日期继续补齐，补齐时每段最多 7 天。日常每轮重查最近 3 天，以 UPSERT 更新延迟上传的记录。

脚本 `deploy/sync_incremental.py` 读取现有唯一有效账号的 API Key，通过本机 `/api/sync` 发起后台同步并轮询最终结果，覆盖全部 8 种数据类型。只有全部类型成功才推进日期；失败返回非零退出码、保留成功进度，下一次整点重新尝试。systemd 单元与文件锁防止同一任务重复运行，API 忙碌时保留待同步日期。

- 进度：`/var/lib/mi-fitness-mcp/incremental-sync.json`，权限 `0600`，不包含凭据或健康测量值。
- 任务用户：`mifitness`；不更改 Hermes、API 或 Web 的运行配置。
- 启用前已额外备份数据库至 `/var/lib/mi-fitness-mcp/backups/before-incremental-timer-*.db`。
- 只能拉取手机 App 已上传到小米云的数据；超过 3 天才补传的旧记录需手动扩大日期范围补同步。

```bash
# 查看下次执行时间和最近一次结果
systemctl list-timers mi-fitness-sync.timer
systemctl status mi-fitness-sync.service --no-pager
journalctl -u mi-fitness-sync.service -n 20 --no-pager

# 手动触发一轮，或暂停后续定时任务
systemctl start mi-fitness-sync.service
systemctl disable --now mi-fitness-sync.timer
```

定向验证：`python -m unittest discover -s tests -p test_incremental_sync.py -v`，覆盖最近日期重查、停机补齐、部分失败续传和接口忙碌时保留进度。

2026-10-18 15:40 实跑通过，范围为 2026-10-16 至 2026-10-18，8 种数据类型全部成功，共处理 709 条记录（含已有记录更新，相比启用前净新增 24 条）。数据库 `PRAGMA quick_check` 返回 `ok`，4 项定向测试通过；定时器已启用，首次定时触发为北京时间 2026-10-18 16:00。首次尝试遇到云端请求失败，未推进成功日期，重新执行后全部成功。

## 2026-10-18 全历史同步

`deploy/sync_full_history.py` 是本次账号截至 2026-10-18 的一次性同步任务。它先备份 SQLite，再探测云端各数据类型的历史年份，通过已有 API 按周强制补齐历史数据；进度文件记录每段结果，重复运行会跳过已完成段。脚本读取现有账号凭据，不将凭据写入进度或日志。

- 备份：`/var/lib/mi-fitness-mcp/backups/before-full-history-20261018.db`，包含凭据，权限为 `0600`。
- 进度：`/var/lib/mi-fitness-mcp/history-sync-20261018.json`。
- 日志：`journalctl -u mi-fitness-history-sync --no-pager`。

启动或续传（先确认同名任务已退出；已退出的 transient unit 若仍存在，先使用新的 unit 名）：

```bash
ssh root@<服务器IP> 'systemd-run --unit=mi-fitness-history-sync \
  --uid=mifitness --gid=mifitness \
  --property=WorkingDirectory=/opt/mi-fitness-mcp-cn/app \
  --property=EnvironmentFile=/etc/mi-fitness-mcp/runtime.env \
  --property=UMask=0077 \
  /opt/mi-fitness-mcp-cn/.venv/bin/python -u \
  /opt/mi-fitness-mcp-cn/app/deploy/sync_full_history.py'
```

任务完成后仍按所选日期查询；在网页将开始日期设为 `2020-03-09` 可查看全部已同步历史。各类型的实际起止日期以 `/api/coverage` 为准，云端没有记录的日期不会补造数据。

本次执行结果：641 个分段全部成功，0 个失败，共 21,930 条记录（活动 1,119、心率 14,601、睡眠 696、运动 7、体重 4、血氧 1,935、压力 3,568）。异常心搏云端无记录；另行查询确认 2026-09-24 至 2026-10-18 的血氧云端记录为 0。数据库 `PRAGMA quick_check` 返回 `ok`，各类型增量游标与最新入库记录一致，API 和 Web 服务保持运行。通过 Web 代理验证了完整活动日期范围及早年的活动、睡眠、心率查询。

## 验证边界

初次部署检查服务启动、页面与代理、静态 Key 和管理 Key 鉴权、Host 白名单、扫码接口及 MCP 工具发现。

2026-10-18 账号授权后已验证实际账号连接、2026-10-17 至 2026-10-18 的每日活动同步及运动记录查询。网页修正通过 7 个 Node 回归用例和 5 个 Web 代理用例，并在隔离的 Chrome 中验证概览、活动表、睡眠分期、指标图表和运动记录响应。
