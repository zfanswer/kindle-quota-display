# Development & Agent Handoff

这份文档面向下载源码后接手二开的开发者和 Agent。它描述当前实现及验证边界，不假定读者拥有原作者的账户、局域网、设备、日志或运行服务。

## 首次接手

1. 读 [README](README.md)、[AGENTS.md](AGENTS.md)、[Spec](docs/spec.md) 和[技术设计](docs/design.md)。
2. 确认任务是离线代码修改、真实采集还是设备部署；不要从旧生成物推断当前环境已获授权。
3. 建立 Python 3.12 环境，安装 `requirements.txt`；Linux 安装 Noto CJK，macOS 可用系统中文字体。
4. 从项目根目录执行 `sh scripts/offline-check.sh`，先得到离线基线。
5. 修改相关模块并运行针对性测试；影响数据、安装或电源行为时同步修改文档。

本项目通过仓库根目录直接运行 Python 模块，不需要 `pip install -e .`。生产采集本身只用标准库；Pillow/字体用于渲染和离线测试。采集器使用 POSIX `fcntl`/进程组，Windows 原生执行未适配。

## 模块地图

| 文件 | 职责 | 修改时要一起检查 |
| --- | --- | --- |
| `quota_display/model.py` | CLI payload → 白名单 snapshot；有限数值、时间、窗口及状态校验 | Schema、fixture、失败缓存及 HTTP 二次过滤 |
| `quota_display/collector.py` | 有界 CLI 子进程、每源超时、锁、独立失败、原子写入 | CodexBar source/字段、stdout 上限、进程清理、退出码 |
| `quota_display/render.py` | 1072×1448 中文 L8 图片、卡片、16 灰阶、固定时间 | PNG 校验、字体选择、第三窗口及无数据布局 |
| `quota_display/server.py` | 只读额度/图片 HTTP；分钟缓存；固定设备遥测 | 路由、响应大小、no-store、遥测白名单与枚举 |
| `kindle/common.sh` | 严格配置、下载/probe、PNG 校验、Wi-Fi 状态、RTC、遥测 | 不执行配置文本、BusyBox 兼容、恢复原状态 |
| `kindle/find-server.sh` | 自动已知地址探测、手动有界私有子网发现、身份匹配、缓存 | CIDR 边界、预算、缓存失效、公网拒绝 |
| `kindle/quota-dashboard.sh` | 生命周期、绘图、RTC 循环、早醒继续与停止清理 | 锁与 PID 归属、Wi-Fi/屏保、其他 RTC alarm |
| `kindle/bootstrap.sh` | 设备能力自检（不要求Mac在线）、启用休眠、启动循环 | 已运行幂等、配置修改、设备能力与状态恢复 |
| `kindle/documents/*.sh` | Scriptlet 用户入口和安装钩子 | `Name`、`DontUseFBInk`、`UseHooks`、日志方式 |
| `scripts/prepare.py` | 只生成 plist 或 Kindle 包与 manifest | 绝对路径、输出范围、参数、默认值 |
| `scripts/install-kindle.py` | macOS USB 目标核验、备份、复制和 hash 核验 | 卷名/挂载点、符号链接、项目文件范围 |
| `scripts/observe-kindle.py` | 只读设备事件，记录有限时间的验收结果 | `not_seen`、重启清空、退出事件和证据边界 |

Docker Compose 的服务名为 `eink-dashboard`，镜像由本项目 `Dockerfile` 构建。容器只读挂载 `runtime/`，非 root 运行，不含 CodexBar、账户凭据或设备执行通道。

## 数据不变量

- Provider 固定为 `codex`、`claude`，各一个当前默认账户。增删 Provider 不能只改配置，需要同步 model、collector、renderer、Schema、tests 和布局。
- CLI 固定 `usage --provider … --source oauth --format json --no-credits`。不要为了“跑通”扩大为 `auto`、web 或任意 source。
- 读取 CodexBar 的 `usage.primary/secondary/tertiary`，将 `usedPercent` 转为 `remaining_percent=max(0,100-used)`，`resetsAt` 转为 `reset_at`；合成占位窗口不显示。
- `attempted_at`、`last_success_at`、`sampled_at` 含义不同。失败不刷新成功数据的时间，另一源继续处理。
- 无成功数据用通用 fallback，不添加订阅状态判断或 `disabled_providers`。
- 输出与 HTTP 再读取都重建白名单，丢弃 account、identity、token、credits、diagnostic、任意上游错误文本及未知字段。
- 时间存 UTC、显示时转时区；重置时间缺失就显示未知，不从窗口长度猜测起点。
- `.env` 由 Compose 消费，Python 模块不会自动加载它；CLI 配置用 `--config`，启动参数/环境变量以各模块 `--help` 为准。

## 建立离线反馈

```sh
sh scripts/offline-check.sh
python -m unittest discover -s tests -v
python -m compileall -q quota_display scripts tests
```

完整离线检查包含 unittest、Shell语法检查、合成snapshot和五种预览。`tests/test_kindle.py` 使用假的 HTTP/LIPC/FBInk/ip/sleep，不允许把测试命令替换成真实设备命令。`tests/fixtures/` 和 `docs/schema/example.json` 都是合成数据。

可单独生成合成输入与图片：

```sh
python -m quota_display.collector \
  --fixture-dir tests/fixtures --fixture-now 2026-10-07T12:00:00Z \
  --output build/preview/quota.json
python scripts/render-previews.py
```

这会更新 `docs/assets/` 中的公开合成预览。不要使用 `runtime/quota.json` 生成将提交到 GitHub 的截图。不同操作系统字体可能使图片字节不同，重点检查尺寸、模式、灰阶、文字与布局。

## 真实验证边界

真实采集、Docker/LAN 服务、launchd 或 USB/RTC 操作按[手顺](docs/runbook.md)在获授权后执行。不要复制个人 Auth 文件给 Agent，也不要将原始 CLI JSON 重定向为调试文件。

| 证据 | 能证明什么 | 不能代替什么 |
| --- | --- | --- |
| 离线 unittest/fixture | 代码分支与数据契约 | Provider 实时接口、网络、硬件 |
| Host HTTP + PNG 检查 | 服务可达、图片规格 | Kindle 下载和显示 |
| `frame_ok` | 设备自报下载/校验/FBInk 成功 | 肉眼看到的方向、残影、内容 |
| `suspend_armed → resumed → frame_ok` | 被记录轮次的自动返回与刷新 | 一小时不中断、电量、停止恢复 |
| 人工设备验收 | 对应场景的实际行为 | 未测试的固件/设备/网络 |

用 [acceptance-record.md](docs/acceptance-record.md) 为每台设备建立本地 `docs/acceptance.local.md`。运行日志、观察摘要、设备备份都留在忽略的 `runtime/`，PR 只写脱敏结论。

## 设备与电源的已知限制

- PW3 1072×1448 是当前唯一适配目标；换分辨率须同时改 renderer 和 `common.sh valid_png`。
- Scriptlets 需要支持 hooks；主入口文件只有函数定义，普通 `sh entry.sh` 不会自动调用 `on_run`。
- 主入口自检通过后将 `ALLOW_SUSPEND=0` 改为 1。若要支持 Wi-Fi 常开模式，需调整 bootstrap 的策略，不能只改配置或删掉关无线语句。
- 省电模式每轮关闭无线、RTC休眠；正常3分钟，连续失败每次加3分钟至15分钟。下一轮有30秒共享网络预算和IPv4就绪判断/已知地址短重试，不自动扫描子网。
- 其他进程占用 wakealarm 时不能覆盖；RTC 设备/epoch 支持按实际驱动核验。
- 早醒只记录为resumed/early_wake，不自动退出。恢复屏保保护、按需重画缓存；无线关闭的20秒短交互后，按硬件RTC截止时间重挂起剩余计划。60秒内3次立即返回或硬件计时异常保护性退出。停止入口可中断等待并恢复原状态，电源键不用于退出循环。
- 固定事件同时写入设备lifecycle.log，达到256KiB时轮换为lifecycle.previous.log；日志在服务器不可达时也保留，不含原始CLI/HTTP数据。
- 临时恢复入口成功绘图两次后删除；Library 重新索引可能滞后。正常操作用四个永久入口。
- 启动先显示最近成功frame.png，无有效缓存则显示固定“正在刷新quota信息”，再联网；已有worker也可恢复画面。show-cache不改Wi-Fi/RTC/进程状态，占位不提交为真实缓存；/tmp不保证跨重启。
- 固定资产在kindle/assets/bootstrap-frame.png，部署到同名设备路径；refresh-v1标记使旧版额度快照被忽略。可用`python -m quota_display.render --placeholder --output kindle/assets/bootstrap-frame.png`重建，不接受quota输入或时间参数。
- 绘图与成功缓存提交由同一display-lock保护，预览不能在新图绘制与提交之间重绘旧图；生命周期锁与绘图锁各司其职。
- 自动只探测缓存/IP/主机名；手动扫描限制实际私有 `/22` 至 `/30`；SERVER_ID 是身份标记而非认证。活动worker的rediscover请求有ID/ready握手，不能用信号单独唤醒mem。

## 二开方向与验证要求

| 方向 | 必须保持/新增的验证 |
| --- | --- |
| 新 Provider/多账户 | 显式账号选择、source 合约、白名单、单源失败；避免跨账户继承缓存 |
| 新设备/分辨率 | PNG 头与布局同步、方向/字体/FBInk、RTC/电源、停止恢复实测 |
| 更可靠重连 | 有界就绪等待、网络失败保留旧图、状态恢复；区分主动关无线与 AP 故障 |
| Wi-Fi 常开模式 | 独立配置与 bootstrap 行为、普通等待、停止恢复、实际耗电测量 |
| LAN 认证 | 服务端与发现/下载/遥测客户端一起设计；不将 secret 写入标准 quota 或公开 fixture |

## 可直接交给 Agent 的 handoff

```text
你正在 kindle-quota-display 源码仓库中工作。
先读 AGENTS.md、DEV.md、docs/spec.md 和 docs/design.md，然后执行离线检查建立基线。

这次目标：<要实现或修复的具体行为>
允许操作：<离线代码修改 / 真实采集 / Docker / launchd / USB设备部署>
设备环境（如涉及）：<型号、固件、FBInk、Scriptlets、分辨率>
验收场景：<触发条件、期望画面/状态、需保留的兼容行为>

不要读取或提交 Auth、cookie、Keychain、真实 quota 或个人日志。
使用合成 fixture 和模拟设备建立反馈；涉及设备的结论区分 mock、HTTP、设备自报与肉眼验收。
生成安装包不等于已部署，不自动执行未经授权的 RTC/USB/服务操作。
完成后同步文档，说明变更、验证及仍需人工或真实设备确认的部分。
```

## 发布

遵循 [发布说明](docs/releasing.md)。`docs/local/` 仅保留本地部署摘要，不是贡献规则或公开文档依赖。临时诊断脚本、测试输出及旧安装包可清理；保留正式tests、运行数据、必要验收证据和回滚备份。本仓库采用 Apache-2.0；第三方来源记录在 [sources.md](docs/references/sources.md)。
