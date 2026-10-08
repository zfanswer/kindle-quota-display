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
| Kindle工作后间隔 | 180秒 | 配置60..3600，实际帧间隔含工作开销 |
| 全屏刷新 | 1800秒 | 配置60..86400，不小于INTERVAL |
| 数据过期 | sampled_at年龄≥600秒 | 按Provider判断 |
| 时区 | Asia/Shanghai | 数据UTC、UI按配置时区转换 |
| PNG | 1072×1448、L8、16灰阶 | 无alpha，客户端上限256KiB |
| 发现 | 实际私有IPv4 /22.. /30 | 最多1022主机、16并发、批次间90秒预算 |
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

## Kindle行为

- 配置逐项解析为数据，不source/eval配置；未知/重复key拒绝。
- probe严格核验协议和SERVER_ID；发现不扩大实际CIDR，不扫描公网或/21及更大网段。
- 单实例锁保护绘图与run。新PNG校验、FBInk解码成功后才提交缓存；失败保留旧画面。
- start启动后台run，refresh只做一轮，stop核验PID归属后请求退出，status只读。
- RTC选择可写且未占用的rtc0/rtc1；相对alarm不支持时尝试硬件epoch，不比较硬件与系统绝对epoch来判断早醒。
- 省电循环关闭无线、mem休眠、唤醒后开启无线等8秒；经过时间少于INTERVAL-30时按提前唤醒退出。
- cleanup恢复开始时的无线/屏保，清理自身alarm/PID/锁；不覆盖他人alarm、不删除活动锁。
- bootstrap先检查活动循环，再真实自检；通过后启用RTC。恢复入口是临时文件，成功两次绘图后删除。

## 验收边界

必须分别记录离线测试、Host服务、设备自报和视觉验收；使用[模板](acceptance-record.md)。真实额度需与CodexBar当前账户对应；无额度的Provider验证通用fallback即可，真实额度正确性另测。

新设备需验证手工绘图、RTC连续唤醒、至少一小时稳定性、full refresh/残影、停止/早醒恢复、网络失败保留旧图、DHCP/换网及回滚。未验证项不写为通过。

不承诺宿主机睡眠时刷新、Docker Desktop自动启动、离线图片动态更新状态、mDNS必然可用、其他Kindle型号/固件兼容、跨隔离网络发现或Wi-Fi常连。
