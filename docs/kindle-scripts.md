# Kindle 脚本功能与使用说明

本页按当前源码说明脚本职责、安装位置、调用关系和日志。验证边界另见[验证说明](validation.md)，安装与回滚步骤见[手顺](runbook.md)。

## 日常怎么用

- 开始显示额度并自动更新：点 **“开启Agent额度”**。先用最近成功缓存遮住Library，无有效缓存则显示“正在刷新quota信息”，再做设备能力检查和启动循环；已有任务只恢复画面，不重复启动。
- 回到正常阅读：点 **“停止 Agent 额度”**，退出循环并恢复启动时的 Wi-Fi、屏保状态。
- 只更新一次图片：循环停止时点 **“刷新 Agent 额度”**，完成后不启动循环。
- 换 Wi-Fi 或怀疑缓存地址失效：点 **“重找额度服务器”**。由活动循环跳过退避、查找并立即刷新；没有循环时只查找和刷新一次。换网或DHCP换IP且主机名失效时需手动重找，后台不扫描。
- **“Agent 额度恢复自检”** 是安装调试期间的临时入口，调用与“开启Agent额度”相同的自检流程，日常无需额外点击。

自动循环成功后设置 180 秒 RTC 待机，连续失败按3分钟递增至15分钟；实际帧间隔还包含唤醒、联网和下载时间。网络或图片校验失败时保留之前的画面。

电源键或其他提前唤醒不作为停止指令：循环保持无线关闭，按需重画缓存，短交互后以剩余RTC时间重新休眠。需要恢复正常阅读时使用“停止 Agent 额度”。

省电循环每轮会主动关闭无线，再在 RTC 唤醒后开启，因此 Wi-Fi 会重新连接，系统界面也可能显示飞行模式。原因、代码路径、复现与证据边界见 [电源与无线行为](power-management.md)。

## 五个 Library 入口

源码位于 `kindle/documents/`，安装到 Kindle 的 `/mnt/us/documents/`；USB 挂载时通常对应 `/Volumes/Kindle/documents/`。界面名称来自脚本的 `# Name:`，因此显示名称与英文文件名不同。

| 源码文件 | Kindle 显示名称 | 调用与功能 | 使用说明 |
| --- | --- | --- | --- |
| [AI Quota Dashboard.sh](../kindle/documents/AI%20Quota%20Dashboard.sh) | 开启Agent额度 | `bootstrap.sh`：先显示最近成功缓存，再做设备能力检查并启动循环，离线也能启动进入退避；已有任务不重复启动 | 日常启动入口；安装钩子也会延迟 10 秒尝试自检启动 |
| [Refresh AI Quota.sh](../kindle/documents/Refresh%20AI%20Quota.sh) | 刷新 Agent 额度 | `quota-dashboard.sh refresh`：发现服务器、下载并校验 PNG、FBInk 绘图、恢复 Wi-Fi | 单次刷新；后台循环或其他刷新持锁时拒绝并发 |
| [Find Quota Server.sh](../kindle/documents/Find%20Quota%20Server.sh) | 重找额度服务器 | `quota-dashboard.sh rediscover`：活动任务接收请求并跳过退避；无任务时独占做单次扫描/刷新 | 仍会探测配置 IP、主机名，再扫描实际子网；本次请求结果写入 `discovery.log` |
| [Stop AI Quota Dashboard.sh](../kindle/documents/Stop%20AI%20Quota%20Dashboard.sh) | 停止 Agent 额度 | `quota-dashboard.sh stop`：写停止标记，对核验过的本项目进程发送终止信号，触发清理 | 恢复启动时的 Wi-Fi、屏保，清理本程序拥有的 RTC alarm、PID 和锁 |
| [Recover Agent Quota.sh](../kindle/documents/Recover%20Agent%20Quota.sh) | Agent 额度恢复自检 | `bootstrap.sh`：与主入口相同，使用独立安装钩子再次触发恢复流程；日志采用追加模式 | 临时恢复入口；后台进程成功绘图累计达到 2 次后删除此 `.sh` 文件 |

**为什么有时看到五个，有时只有四个？** 恢复包带第五个临时入口，正常运行后代码会删除它；Library 条目消失时间还取决于设备重新索引。永久入口是其余四个。源码和历史安装包仍保留恢复脚本，设备自动删除不改变本地源码。

主入口和恢复入口使用 `on_install()` / `on_run()` 钩子，由现有 Scriptlet 集成调用。直接用 `sh` 执行这两个入口文件只会定义函数；在设备终端调试时应调用内部 `bootstrap.sh`，或从 Library 点击入口。

## 四个内部脚本

源码位于 `kindle/`，安装到 `/mnt/us/eink-dashboard/`；USB 挂载时通常对应 `/Volumes/Kindle/eink-dashboard/`。由入口或后台进程调用。

| 源码文件 | 职责 | 关键行为 |
| --- | --- | --- |
| [bootstrap.sh](../kindle/bootstrap.sh) | 启动前自检与引导 | 先show-cache显示最近成功缓存，再检查活动循环；未运行时检查FBInk、无线/屏保属性及RTC/power能力，通过后启用休眠并start；网络成功不是启动前提 |
| [quota-dashboard.sh](../kindle/quota-dashboard.sh) | 生命周期、绘图与自动循环 | 管理锁/PID、下载校验、FBInk、普通/全屏刷新、RTC 休眠与唤醒、退出清理和设备回报 |
| [find-server.sh](../kindle/find-server.sh) | 查找并核验额度服务器 | 默认/--known-only为缓存 → 配置 IP → 配置主机名；只有--force且ENABLE_SCAN=1才允许实际私有子网扫描；核对 `/healthz` 的协议标识及 `SERVER_ID`，成功后原子更新 `server.cache` |
| [common.sh](../kindle/common.sh) | 公共函数库 | 严格读取配置数据，提供 IP/主机名校验、HTTP 下载、服务器身份探测、PNG 头校验、Wi-Fi 保存/恢复、RTC 设置和固定诊断回报；由其余脚本 `source` 使用 |

`find-server.sh` 默认和`--known-only`只探测已知地址；`--force`跳过缓存、允许手动扫描（与--known-only互斥），`--internal`表示Wi-Fi由调用者管理。扫描仅支持实际 RFC1918 私有 IPv4 `/22` 至 `/30`，最多 1022 个可用地址、16 并发、共用90秒扫描预算及120秒手动网络总预算；优先当前 `/24` 与实际子网的交集，不猜测或扩大网段。

`quota-dashboard.sh` 支持以下动作：

| 动作 | 功能 |
| --- | --- |
| `start`（默认） | 获取单实例锁，启动后台 `run`；已有本项目循环时返回成功 |
| `run` | 后台工作循环；`ALLOW_SUSPEND=1` 使用 RTC 和系统休眠，`0` 使用普通等待并保持 Wi-Fi 开启。由 `start` 启动，日常不直接调用 |
| `refresh` | 单次刷新，只探测已知地址，需要独占锁，不启动自动循环 |
| `rediscover` | 活动worker接收固定请求ID并跳过等待扫描/刷新；没有worker时只做一轮；合并待办请求，不启动新循环 |
| `show-cache` | 优先显示最近成功frame.png，没有有效缓存则显示带标记的固定占位图；不联网、不动RTC/进程状态、不提交占位图为缓存；绘图繁忙时跳过 |
| `stop` | 请求活动循环退出，仅对核验属于本项目的 PID 发信号 |
| `status` | 输出 `running pid=…` 或 `not running`，以及最近的本地状态，不刷新图片 |

当前配置默认 `FULL_REFRESH=1800`：距离最近一次成功全屏刷新达到 30 分钟后，在下一次成功绘图时进行全屏刷新。成功下载及解码前不提前清空旧画面。

## 调用关系

```text
开启Agent额度 / Agent 额度恢复自检
  └─ bootstrap.sh
       ├─ quota-dashboard.sh show-cache → 最近成功 PNG / 固定刷新占位 → FBInk
       ├─ quota-dashboard.sh status
       ├─ 设备能力检查（无须服务器在线）
       └─ quota-dashboard.sh start → 后台 run → 刷新 → RTC 待机 → 唤醒 → 下一轮

刷新 Agent 额度 → quota-dashboard.sh refresh
重找额度服务器 → quota-dashboard.sh rediscover → 活动worker请求 / 单次独占 → find-server.sh --force → 刷新
停止 Agent 额度 → quota-dashboard.sh stop → 后台进程清理

bootstrap.sh / quota-dashboard.sh / find-server.sh → common.sh
```

## 配置、缓存与日志在哪

以下为 Kindle 内部路径；USB 挂载时将 `/mnt/us` 换为挂载根目录，例如 `/Volumes/Kindle`。

| 文件/目录 | 内容与用途 |
| --- | --- |
| `/mnt/us/eink-dashboard/server.conf` | 服务器 IP/主机名、端口、身份标识、手动扫描许可、刷新间隔、全屏刷新间隔、FBInk 路径、休眠开关；严格作为数据解析 |
| `/mnt/us/eink-dashboard/server.cache` | 最近找到的有效服务器地址，与配置分开保存 |
| `/mnt/us/eink-dashboard/bootstrap-frame.png` | 固定“正在刷新quota信息”占位图，不含额度/时间；只在无有效缓存时使用。有refresh-v1标记，旧版同名额度快照会被忽略 |
| `/mnt/us/eink-dashboard/bootstrap.log` | 主入口/恢复入口的自检输出；主入口每次调用覆盖，恢复入口追加 |
| `/mnt/us/eink-dashboard/run.log`、`run.previous.log` | 后台输出，每轮检查256KiB轮换 |
| `/mnt/us/eink-dashboard/power.log`、`power.previous.log` | 每轮failures/next_delay/cycles摘要，256KiB轮换 |
| `/mnt/us/eink-dashboard/lifecycle.log`、`lifecycle.previous.log` | 固定启动/绘图/休眠/唤醒/退出事件，含系统epoch；服务器离线时也保留。当前文件达到256KiB后轮换，仅保留当前和上一份 |
| `/mnt/us/eink-dashboard/discovery.log` | 手工重找的最后一次结果：成功为 `Rediscovered and refreshed`，失败为对应请求失败/超时或发现输出 |
| `/tmp/kindle-quota-display/` | 临时PID/ready、固定ID request/result、生命周期锁、display-lock、停止标记、状态、最近成功frame.png和全屏刷新时间；停止保留图片，重启可能清除；不是USB用户存储目录 |

USB 模式下可回读持久日志，临时运行状态在设备端检查。Library 可能隐藏标准输出，脚本失败时保留旧画面，仅凭屏幕没变化不能判断发现是否成功。后台循环活动时普通单次刷新会提示 `Dashboard already active`，手动重找使用worker请求通道，可跳过退避。

Mac 上的设备回报是服务器收到的固定诊断事件，使用 `/api/device/kindle1` 和 `/api/device/kindle1/history` 读取，与设备本地日志互补。`frame_ok` 表示设备自报绘图命令成功，视觉效果仍由肉眼确认。

## 本地目录与安装目录的对应

```text
本地 kindle/documents/*.sh  → Kindle /mnt/us/documents/*.sh
本地 kindle/*.sh            → Kindle /mnt/us/eink-dashboard/*.sh
本地 kindle/assets/bootstrap-frame.png → Kindle /mnt/us/eink-dashboard/bootstrap-frame.png
本地 server.conf.example    → 生成包内 server.conf → Kindle 配置
本地 build/kindle-*/        → 各次生成的安装包副本，含 manifest.json
```

修改本地源码不会自动更新 Kindle，须重新生成安装包并按手顺使用--update部署，保留设备配置/地址缓存且不重加临时恢复入口。历史 `build/` 包和 `runtime/backups/` 是生成物/备份，日常阅读代码以 `kindle/` 为准。
