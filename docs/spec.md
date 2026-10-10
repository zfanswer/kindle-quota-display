# 行为 Spec — V1

本文件定义当前实现的契约。面向PW3 1072×1448竖屏、Codex和Claude各一个当前默认账户。第三方接口由CodexBar适配，不宣称OAuth额度端点是永久稳定的公开API。

## 默认配置

| 参数 | 默认值 | 约束 |
| --- | --- | --- |
| CLI来源 | oauth | 固定，不自动降级到auto/web |
| 每源timeout | 30秒 | 配置允许1..45秒，串行两源 |
| CLI stdout上限 | 1MiB | 有界读取，失败/完成清理进程组 |
| launchd间隔 | 180秒 | StartInterval，无KeepAlive |
| HTTP | 8486 | Compose默认127.0.0.1发布，容器内0.0.0.0监听 |
| Kindle成功后间隔 | 180秒 | INTERVAL配置60..3600，实际帧间隔含工作开销 |
| 失败后RTC等待 | 180、360、540、720、900秒 | 每个失败轮次增加3分钟，上限15分钟；成功清零 |
| 网络工作预算 | 自动30秒，手动120秒 | 无线就绪、已知地址、PNG、在线遥测共享预算；收尾/FBInk另有短超时 |
| 全屏刷新 | 1800秒 | 配置60..86400，不小于INTERVAL |
| 数据过期 | sampled_at年龄≥600秒 | 按Provider判断 |
| 时区 | Asia/Shanghai | 数据UTC、UI按配置时区转换 |
| PNG | 1072×1448、L8、16灰阶 | 无alpha，客户端上限256KiB |
| 自动发现 | 缓存、配置IP、主机名 | 每次候选去重，最多3次短探测；永不扫描子网 |
| 手动扫描 | 实际私有IPv4 /22.. /30 | 最多1022主机、16并发、90秒扫描预算，且受120秒网络总预算限制 |
| 休眠 | 配置模板0 | 主入口自检成功改为1，再启动RTC循环 |

## 数据契约

[JSON Schema](schema/quota-v1.schema.json)描述结构，[合成示例](schema/example.json)用于理解；`model.validate_snapshot`另执行有限数值、唯一窗口和状态一致性校验。

根对象包含schema_version=1、updated_at和providers（codex、claude）。未知字段在标准化与读取端丢弃。所有日期含时区，输出UTC Z。

每源包含name、source、status、attempted_at、last_success_at、sampled_at、error_code、windows。成功时有真实窗口及成功/采样时间，error_code=null。失败时是固定error_code，可保留上次好数据；首次失败时间为null、windows为空。

窗口id为primary/secondary/tertiary，最多三个且唯一。used_percent是有限非负值，remaining_percent=max(0,100-used)；允许超过100%的used值。window_minutes为正整数或null，reset_at为ISO日期或null。上游isSyntheticPlaceholder=true的窗口不显示。

固定错误：timeout、command_failed、invalid_payload、source_mismatch、cli_missing、output_limit。任意源失败时collector退出1，但仍原子写入完整snapshot；不要把退出1理解为另一源成功数据未保存。

无额度采用通用fallback，首轮无数据或保留历史数据，不做订阅状态、disabled_providers或自动账号切换。

## HTTP契约

| 路径 | 行为 |
| --- | --- |
| GET /healthz | 200 text；EINK_QUOTA_V1和SERVER_ID两行，不代表额度健康 |
| GET /api/quota | 200标准snapshot；无法读取有效数据时503 |
| GET /frame/kindle1.png | 200中文PNG；无数据也生成暂无数据画面；渲染异常500 |
| GET /api/device/kindle1 | 最近固定事件或not_seen |
| GET /api/device/kindle1/history | 最多128条内存事件，服务重启清空 |
| POST /api/device/kindle1 | 固定遥测，输入≤1024字节，非法字段/枚举/命令拒绝 |
| 其他路由 | 404或标准HTTP不支持响应，无执行/文件浏览/额度写入 |

成功响应明确Content-Length和no-store；PNG带诊断ETag，客户端不依赖条件请求。遥测包含stage/reason/interval/cycles，可带rtc_device、rtc_epoch、system_epoch、alarm_epoch、elapsed_seconds；类型和范围受限。

stage为bootstrap、preflight_failed、frame_ok、refresh_failed、suspend_armed、resumed、stopped；reason由服务端固定枚举定义。遥测不鉴权、非权威，不能更改额度或执行设备命令。

## PNG显示

每个Provider一张卡片。右上角以26px黑色粗体显示原始sampled_at转换后的“数据更新 YYYY-MM-DD HH:MM”，替代原状态位置；“正常”“采集失败”“数据过期”等移到标题下的次要行。没有成功采样时显示“尚无成功采集”，固定启动图显示“等待更新”，不制造时间。重置时间仍为绝对时刻，不显示实时钟、相对年龄或冻结倒计时。

## Kindle行为

- 配置逐项解析为数据，不source/eval配置；未知/重复key拒绝。不增加退避配置或作息时段。
- 自动worker、普通refresh以及find-server默认只探测缓存、配置IP、主机名；候选去重，最多3次短探测，重试间隔最多2秒且共享总预算。始终核验healthz协议和SERVER_ID。
- 仅显式手动rediscover / find-server --force允许扫描，且需ENABLE_SCAN=1；--known-only与--force互斥。手动扫描不扩大实际CIDR，不扫描公网或/21及更大网段。网络变化、DHCP换IP且主机名失效时由用户手动重找。
- 连续失败按完整刷新轮次计数，上限5。下一等待为min(failures,5)×180秒；首轮失败180秒。只有有效PNG成功解码、绘图并原子提交后清零，成功等待INTERVAL。有效“暂无数据”PNG算成功；多个候选失败后成功仍算成功。停止/取消不算失败；重新开启或重启清零。
- 单实例锁保护run/refresh/单次rediscover，独立display-lock保护绘图和缓存提交。坏图、下载或解码失败不清屏、不覆盖成功frame.png。常规失败不反复重画旧图。
- 启动先show-cache显示最近成功frame.png；缓存缺失、无效或解码失败时使用固定卡片式bootstrap-frame.png，提示“正在刷新quota信息”。必须有refresh-v1标记；旧版同名额度快照被忽略。占位不提交为frame.png，/tmp缓存不保证跨重启。show-cache不联网、不动RTC/任务状态，绘图繁忙时跳过。
- bootstrap把设备能力与服务器在线状态分开：检查FBInk可执行、无线/屏保状态可读、可写power、空闲RTC及可读硬件时间。通过后启用RTC并start；Mac离线也能进入失败退避。已有ready worker时只恢复画面，不重复启动。
- 每轮network_begin建立基于/proc/uptime的30秒预算；手动为120秒。Wi-Fi开启后有界等待有效IPv4；IPv4并不代表服务器可达。每个HTTP请求同时受剩余预算和外层watchdog限制，包括wget解析卡住的情况。FBInk最多10秒、设备属性命令最多3秒，超时终止有1秒强制回收宽限；网络预算不是整机清醒时间硬上限。
- RTC arm_rtc(delay)只选择空闲可写rtc0/rtc1，相对alarm不支持时使用硬件epoch。180–900秒退避关闭无线并mem休眠；ALLOW_SUSPEND=0仅为明确的诊断模式，使用普通等待。线上成功后的INTERVAL不被退避改写。
- 等待使用同一个RTC的since_epoch和实际alarm截止时间，不比较RTC与系统epoch。提前返回先检查停止/手动请求及截止时间，重新保持屏保保护，必要时show-cache，再在无线关闭的最多20秒交互窗口后以剩余时间重新挂起；不增加失败计数。系统墙钟调整不延长等待。
- 60秒内连续3次挂起持续0–2秒且无手动请求，或明确挂起/硬件计时失败时，以suspend_failed退出并归还原生电源管理；此故障例外可能恢复Kindle原生待机页。单次普通早醒不退出。
- 活动worker安装USR1/停止处理后发布pid和ready。手动入口原子发布固定请求ID并只通知经cmdline/ready核验的worker；由worker跳过退避、单独扫描/刷新。重复待办合并，结果按请求ID匹配；没有worker时只做一轮，不启动循环。信号本身不能唤醒mem，Library操作须先让设备醒来。停止优先，不移除活动/遗留锁。
- cleanup终止并回收拥有的命令、探测子进程和短等待，只有wakealarm仍匹配自己的alarm时才清除，恢复原无线/屏保，清理PID/ready/锁。停止不为遥测重新开启无线。
- lifecycle.log保存原固定遥测事件；power.log每轮只记失败数/下一间隔/成功轮数，各达到256KiB时轮换并仅保留当前/上一份。已知不可达、休眠及停止时只记本地，不HTTP POST；连接成功且预算有余时上报，不补发旧事件、不扩展HTTP Schema。run.log的输出也在每轮达到256KiB时轮换。
- 临时恢复入口成功绘图两次后删除；设备增量更新不重新添加它，保留个人server.conf/server.cache。

## 验收边界

必须分别记录离线测试、Host服务、设备自报和视觉验收；使用[模板](acceptance-record.md)。真实额度需与CodexBar当前账户对应；无额度的Provider验证通用fallback即可，真实额度正确性另测。

新设备需验证手工绘图、RTC连续唤醒、至少一小时稳定性、full refresh/残影、停止恢复、早醒继续刷新、网络失败保留旧图、DHCP/换网及回滚。未验证项不写为通过。

不承诺宿主机睡眠时刷新、Docker Desktop自动启动、离线图片动态更新状态、mDNS必然可用、其他Kindle型号/固件兼容、跨隔离网络发现或Wi-Fi常连。
