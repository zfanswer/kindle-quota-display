# Kindle 脚本功能与使用说明

本页按当前源码说明脚本职责、安装位置、调用关系和日志。验证边界另见[验证说明](validation.md)，安装与回滚步骤见[手顺](runbook.md)。

## 日常怎么用

- 开始显示额度并自动更新：点 **“Agent 额度”**。先自检，再启动后台循环；已经运行时不会重复启动。
- 回到正常阅读：点 **“停止 Agent 额度”**，退出循环并恢复启动时的 Wi-Fi、屏保状态。
- 只更新一次图片：循环停止时点 **“刷新 Agent 额度”**，完成后不启动循环。
- 换 Wi-Fi 或怀疑缓存地址失效：点 **“重找额度服务器”**。找到服务器后保存新地址并尝试刷新；若后台循环正在运行，手工刷新会被锁拒绝，已有循环使用新地址继续刷新。
- **“Agent 额度恢复自检”** 是安装调试期间的临时入口，调用与“Agent 额度”相同的自检流程，日常无需额外点击。

自动循环每轮工作结束后设置 180 秒 RTC 待机；实际帧间隔还包含唤醒、联网和下载时间。网络或图片校验失败时保留之前的画面。

省电循环每轮会主动关闭无线，再在 RTC 唤醒后开启，因此 Wi-Fi 会重新连接，系统界面也可能显示飞行模式。原因、代码路径、复现与证据边界见 [电源与无线行为](power-management.md)。

## 五个 Library 入口

源码位于 `kindle/documents/`，安装到 Kindle 的 `/mnt/us/documents/`；USB 挂载时通常对应 `/Volumes/Kindle/documents/`。界面名称来自脚本的 `# Name:`，因此显示名称与英文文件名不同。

| 源码文件 | Kindle 显示名称 | 调用与功能 | 使用说明 |
| --- | --- | --- | --- |
| [AI Quota Dashboard.sh](../kindle/documents/AI%20Quota%20Dashboard.sh) | Agent 额度 | `bootstrap.sh`：自检、单次真实刷新、检查状态恢复，然后启动后台循环 | 日常启动入口；安装钩子也会延迟 10 秒尝试自检启动 |
| [Refresh AI Quota.sh](../kindle/documents/Refresh%20AI%20Quota.sh) | 刷新 Agent 额度 | `quota-dashboard.sh refresh`：发现服务器、下载并校验 PNG、FBInk 绘图、恢复 Wi-Fi | 单次刷新；后台循环或其他刷新持锁时拒绝并发 |
| [Find Quota Server.sh](../kindle/documents/Find%20Quota%20Server.sh) | 重找额度服务器 | `find-server.sh --force`：跳过旧缓存探测，查找并保存地址；成功后尝试 `refresh` | 仍会探测配置 IP、主机名，再扫描实际子网；最后结果写入 `discovery.log` |
| [Stop AI Quota Dashboard.sh](../kindle/documents/Stop%20AI%20Quota%20Dashboard.sh) | 停止 Agent 额度 | `quota-dashboard.sh stop`：写停止标记，对核验过的本项目进程发送终止信号，触发清理 | 恢复启动时的 Wi-Fi、屏保，清理本程序拥有的 RTC alarm、PID 和锁 |
| [Recover Agent Quota.sh](../kindle/documents/Recover%20Agent%20Quota.sh) | Agent 额度恢复自检 | `bootstrap.sh`：与主入口相同，使用独立安装钩子再次触发恢复流程；日志采用追加模式 | 临时恢复入口；后台进程成功绘图累计达到 2 次后删除此 `.sh` 文件 |

**为什么有时看到五个，有时只有四个？** 恢复包带第五个临时入口，正常运行后代码会删除它；Library 条目消失时间还取决于设备重新索引。永久入口是其余四个。源码和历史安装包仍保留恢复脚本，设备自动删除不改变本地源码。

主入口和恢复入口使用 `on_install()` / `on_run()` 钩子，由现有 Scriptlet 集成调用。直接用 `sh` 执行这两个入口文件只会定义函数；在设备终端调试时应调用内部 `bootstrap.sh`，或从 Library 点击入口。

## 四个内部脚本

源码位于 `kindle/`，安装到 `/mnt/us/eink-dashboard/`；USB 挂载时通常对应 `/Volumes/Kindle/eink-dashboard/`。由入口或后台进程调用。

| 源码文件 | 职责 | 关键行为 |
| --- | --- | --- |
| [bootstrap.sh](../kindle/bootstrap.sh) | 启动前自检与引导 | 检查是否已有活动循环；可先显示安装时附带的真实启动图，再真实下载刷新；核对 Wi-Fi、屏保恢复和 RTC 可用性；通过后将 `ALLOW_SUSPEND=0` 改为 `1` 并调用 `start`。失败时退出并回报固定原因 |
| [quota-dashboard.sh](../kindle/quota-dashboard.sh) | 生命周期、绘图与自动循环 | 管理锁/PID、下载校验、FBInk、普通/全屏刷新、RTC 休眠与唤醒、退出清理和设备回报 |
| [find-server.sh](../kindle/find-server.sh) | 查找并核验额度服务器 | 顺序为缓存 → 配置 IP → 配置主机名 → 实际私有子网扫描；核对 `/healthz` 的协议标识及 `SERVER_ID`，成功后原子更新 `server.cache` |
| [common.sh](../kindle/common.sh) | 公共函数库 | 严格读取配置数据，提供 IP/主机名校验、HTTP 下载、服务器身份探测、PNG 头校验、Wi-Fi 保存/恢复、RTC 设置和固定诊断回报；由其余脚本 `source` 使用 |

`find-server.sh` 的 `--force` 只跳过缓存，`--internal` 表示 Wi-Fi 由调用者管理。扫描仅支持实际 RFC1918 私有 IPv4 `/22` 至 `/30`，最多 1022 个可用地址、16 并发、每批检查 90 秒扫描预算；优先当前 `/24` 与实际子网的交集，不猜测或扩大网段。

`quota-dashboard.sh` 支持以下动作：

| 动作 | 功能 |
| --- | --- |
| `start`（默认） | 获取单实例锁，启动后台 `run`；已有本项目循环时返回成功 |
| `run` | 后台工作循环；`ALLOW_SUSPEND=1` 使用 RTC 和系统休眠，`0` 使用普通等待并保持 Wi-Fi 开启。由 `start` 启动，日常不直接调用 |
| `refresh` | 单次刷新并清理，需要独占锁，不启动自动循环 |
| `stop` | 请求活动循环退出，仅对核验属于本项目的 PID 发信号 |
| `status` | 输出 `running pid=…` 或 `not running`，以及最近的本地状态，不刷新图片 |

当前配置默认 `FULL_REFRESH=1800`：距离最近一次成功全屏刷新达到 30 分钟后，在下一次成功绘图时进行全屏刷新。成功下载及解码前不提前清空旧画面。

## 调用关系

```text
Agent 额度 / Agent 额度恢复自检
  └─ bootstrap.sh
       ├─ quota-dashboard.sh status
       ├─ quota-dashboard.sh refresh → find-server.sh --internal → HTTP PNG → FBInk
       └─ quota-dashboard.sh start → 后台 run → 刷新 → RTC 待机 → 唤醒 → 下一轮

刷新 Agent 额度 → quota-dashboard.sh refresh
重找额度服务器 → find-server.sh --force → 保存新地址 → 尝试 refresh
停止 Agent 额度 → quota-dashboard.sh stop → 后台进程清理

bootstrap.sh / quota-dashboard.sh / find-server.sh → common.sh
```

## 配置、缓存与日志在哪

以下为 Kindle 内部路径；USB 挂载时将 `/mnt/us` 换为挂载根目录，例如 `/Volumes/Kindle`。

| 文件/目录 | 内容与用途 |
| --- | --- |
| `/mnt/us/eink-dashboard/server.conf` | 服务器 IP/主机名、端口、身份标识、扫描开关、刷新间隔、全屏刷新间隔、FBInk 路径、休眠开关；严格作为数据解析 |
| `/mnt/us/eink-dashboard/server.cache` | 最近找到的有效服务器地址，与配置分开保存 |
| `/mnt/us/eink-dashboard/bootstrap-frame.png` | 安装时附带的真实额度启动图；成功联网后由当前服务器图片更新屏幕 |
| `/mnt/us/eink-dashboard/bootstrap.log` | 主入口/恢复入口的自检输出；主入口每次调用覆盖，恢复入口追加 |
| `/mnt/us/eink-dashboard/run.log` | 后台循环输出，追加记录 |
| `/mnt/us/eink-dashboard/discovery.log` | 手工重找的最后一次结果：成功为 `FOUND 地址`，失败为发现脚本输出；不包含随后刷新动作的输出 |
| `/tmp/kindle-quota-display/` | 临时 PID、锁、停止标记、状态、好图片缓存和全屏刷新时间；不是 USB 用户存储目录 |

USB 模式下可回读持久日志，临时运行状态在设备端检查。Library 可能隐藏标准输出，脚本失败时保留旧画面，仅凭屏幕没变化不能判断发现是否成功。后台循环活动时手工刷新会提示 `Dashboard already active`，发现成功保存的新地址仍可供下一轮使用。

Mac 上的设备回报是服务器收到的固定诊断事件，使用 `/api/device/kindle1` 和 `/api/device/kindle1/history` 读取，与设备本地日志互补。`frame_ok` 表示设备自报绘图命令成功，视觉效果仍由肉眼确认。

## 本地目录与安装目录的对应

```text
本地 kindle/documents/*.sh  → Kindle /mnt/us/documents/*.sh
本地 kindle/*.sh            → Kindle /mnt/us/eink-dashboard/*.sh
本地 server.conf.example    → 生成包内 server.conf → Kindle 配置
本地 build/kindle-*/        → 各次生成的安装包副本，含 manifest.json
```

修改本地源码不会自动更新 Kindle，须重新生成安装包并按手顺部署。历史 `build/` 包和 `runtime/backups/` 是生成物/备份，日常阅读代码以 `kindle/` 为准。
