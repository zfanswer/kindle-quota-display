# 验证范围与边界

## 离线检查

入口为 `sh scripts/offline-check.sh`。当前62项unittest覆盖标准化、白名单、源/窗口/时钟/数值异常、独立失败缓存、CLI超时/退出/1MiB上限、进程组清理、原子写入与锁、HTTP路由/缓存、PNG尺寸/灰阶、生成器输出限制、USB目标校验、CIDR发现和RTC模拟。

Shell行为测试使用假的HTTP/LIPC/FBInk/RTC，覆盖3→6→9→12→15分钟退避/成功复位、自动不扫描/候选去重、手动/22与/28边界、离线bootstrap、无IPv4总预算、curl/wget卡住超时、手动请求/重复点击、停止回收子进程、坏PNG/解码失败留缓存、绘图/提交并发、早醒剩余RTC重挂起、立即返回保护、系统钟调整和离线日志轮换。另验证黑色右上角原采样时间与标题不重叠、增量安装保留配置和新会话观察边界。

另外执行Shell语法检查、合成采集、五种中文预览。GitHub Actions运行同一离线入口，不要求真实账户、Kindle或项目凭据。CI首次运行是否通过应以GitHub上的结果为准。

| 合成预览 | 场景 |
| --- | --- |
| [正常](assets/preview.png) | 两个Provider各两窗口 |
| [失败缓存](assets/cached-error.png) | 采集失败保留旧数据 |
| [过期](assets/stale.png) | sampled_at超过新鲜度阈值 |
| [无数据](assets/unavailable.png) | 没有有效snapshot |
| [第三窗口](assets/third-window.png) | 三窗口布局、未知时间 |

所有公开预览和fixtures均为合成数据。离线结果不能宣称Provider接口或硬件已验收。

最近完整复验为2026-10-10：macOS和干净公开源码的无网络Linux容器均通过62项测试、Shell语法检查、合成采集和五种预览。Linux使用已预装Python/Pillow/Noto的环境；公开源码不带.env、runtime、build或docs/local。此结果不代表GitHub云端CI已运行。

## 本次部署与验收

2026-10-10已更新Mac Docker图片服务，Host health/PNG均为200、1072×1448 L8/16灰阶。PW3以--update替换9个项目文件，逐文件SHA256核验，server.conf/server.cache未变，未重加临时恢复入口，并已安全推出。安装报告与回滚备份仅在忽略的runtime中。

新版由用户重新启动后收到2次frame_ok，间隔193秒；实际suspend_armed的alarm与同一RTC时间差为180秒，第二帧后再次设置休眠。此证据仅确认已记录的一轮自动刷新，不等于全部RTC返回、视觉或一小时稳定性。剩余RTC重挂起、手动换网和整夜功耗须分别实测，不能将下面旧会话经验当成本次新版全部验收。

## 既有真机经验

当前经验来自macOS、Docker和一台PW3，不能扩展为所有设备兼容。

| 范围 | 已取得的证据 | 尚不能宣称 |
| --- | --- | --- |
| 额度与服务 | 真实Codex标准额度、LAN中文PNG；Claude使用无额度fallback | Claude真实额度正确性 |
| 安装与画面 | Scriptlet/FBInk绘图及用户视觉确认；缓存、固定占位和早醒修复已USB部署并SHA256核验 | 所有固件/型号的显示、方向和残影表现 |
| RTC循环 | 既有短期自动返回记录；最近会话4次frame_ok跨18分21秒，无收到stopped；用户确认超过原故障窗口仍为额度图 | 每轮成功联网、所有RTC返回或连续一小时稳定性；该会话仅收到一次resumed且存在回报空白 |
| 提前唤醒 | 旧版早醒退出有设备记录；新版继续运行有离线回归覆盖 | 新版真实早醒恢复已完成专项验收 |
| 换网与重连 | 曾恢复新网访问；Wi-Fi未连接后恢复并刷新 | 所有DHCP/换网场景自动恢复；新版有界就绪/已知地址重试仍需实际AP验证 |

全屏刷新残影、停止状态恢复、实际功耗、长时间稳定性、不同固件及其他型号仍须单独验收。启动被遗留锁拒绝的恢复手顺见[runbook](runbook.md)。

新用户按[手顺](runbook.md)使用自己的环境并填写[验收模板](acceptance-record.md)。个人部署摘要、最近安装报告、有限验收证据和必要回滚备份留在忽略的docs/local及runtime，不随源码公开；通用行为以Spec和技术设计为准。
