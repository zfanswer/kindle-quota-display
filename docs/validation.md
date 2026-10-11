# 验证范围与边界

## 离线检查

入口为 `sh scripts/offline-check.sh`。当前77项unittest覆盖标准化、白名单、按Provider固定的来源、每源采集间隔、源/窗口/时钟/数值异常及越界时间戳、独立失败缓存、CLI超时/退出/1MiB上限、进程组清理、原子写入与锁、HTTP路由/缓存、空闲连接不阻塞health、PNG尺寸/灰阶、生成器输出限制、USB目标校验、CIDR发现和RTC模拟。

Shell行为测试使用假的HTTP/LIPC/FBInk/RTC，覆盖3→6→9→12→15分钟退避/成功复位、退避步长跟随INTERVAL（300秒、超过15分钟及小于3分钟的间隔）、自动不扫描/候选去重、手动/22与/28边界、离线bootstrap、无IPv4总预算、curl/wget卡住超时、手动请求/重复点击、停止回收子进程、停止后安装钩子不重启/不重画、坏PNG/解码失败留缓存、绘图/提交并发、首轮后重画以覆盖Library重绘、早醒即停止并保留停止标记、立即返回同样停止、2秒内按到期、系统钟调整和离线日志轮换。另验证黑色右上角原采样时间与标题不重叠、增量安装保留配置和新会话观察边界。

另外执行Shell语法检查、合成采集、五种中文预览。GitHub Actions运行同一离线入口，不要求真实账户、Kindle或项目凭据。CI首次运行是否通过应以GitHub上的结果为准。

| 合成预览 | 场景 |
| --- | --- |
| [正常](assets/preview.png) | 两个Provider各两窗口 |
| [失败缓存](assets/cached-error.png) | 采集失败保留旧数据 |
| [过期](assets/stale.png) | sampled_at超过新鲜度阈值 |
| [无数据](assets/unavailable.png) | 没有有效snapshot |
| [第三窗口](assets/third-window.png) | 三窗口布局、未知时间 |

所有公开预览和fixtures均为合成数据。离线结果不能宣称Provider接口或硬件已验收。

最近完整复验为2026-10-10：macOS和干净公开源码的无网络Linux容器均通过62项测试、Shell语法检查、合成采集和五种预览。Linux使用已预装Python/Pillow/Noto的环境；公开源码不带.env、runtime、build或docs/local。此结果不代表GitHub云端CI已运行。此后新增的12项（越界时间戳、空闲连接、来源与间隔、按Provider的过期阈值、plist间隔、同长窗口标签、退避步长、停止标记与安装钩子、早醒即停止、首轮后重画）仅在macOS本地随77项离线检查通过，Linux容器未重跑。

## 本次部署与验收

2026-10-10已更新Mac Docker图片服务，Host health/PNG均为200、1072×1448 L8/16灰阶。PW3以--update替换9个项目文件，逐文件SHA256核验，server.conf/server.cache未变，未重加临时恢复入口，并已安全推出。安装报告与回滚备份仅在忽略的runtime中。

新版由用户重新启动后收到2次frame_ok，间隔193秒；实际suspend_armed的alarm与同一RTC时间差为180秒，第二帧后再次设置休眠。此证据仅确认已记录的一轮自动刷新，不等于全部RTC返回、视觉或一小时稳定性。剩余RTC重挂起、手动换网和整夜功耗须分别实测，不能将下面旧会话经验当成本次新版全部验收。

2026-10-11调整采集：Codex保持oauth、每300秒；Claude改为cli来源、每900秒，launchd任务以300秒间隔和默认优先级重装，图片服务重建。真实采集中两源均为ok，Claude首次取得真实窗口，launchd下单次约14秒；此前以Background优先级运行时Claude超过30秒超时。Host的/api/quota与PNG为200。曾尝试读取CodexBar App的小组件快照以避免运行CLI，因macOS对每个新进程弹出“访问其他 App 的数据”授权而放弃。切换后的Kindle画面未做肉眼验收。同日经USB将设备server.conf的INTERVAL由180改为300（先备份，仅此一行变化，并用设备脚本的解析器校验）；随后以--update把跟随INTERVAL的退避脚本部署到设备：9个文件逐一SHA256核验，实际内容变化的只有quota-dashboard.sh，server.conf未变，临时恢复入口未重加。新间隔随后已有设备回报（interval=300）。第二次--update部署了早醒即停止和停止后安装钩子不重启的脚本，同样逐文件核验；用户在真机上确认：按电源键唤醒后循环停止、设备可正常操作；同时发现点击入口后Library重绘会盖住首帧，设备带着Library画面休眠直到下一轮，已加入首轮后重画并以--update部署（仅quota-dashboard.sh变化，逐文件核验），其真机效果尚未确认。设备lifecycle.log记录了早醒即停止的三次实例（按电源键两次、插USB一次，均为resumed/early_wake后紧跟stopped/early_wake），以及INTERVAL=300下两次按时返回（elapsed=300）。新退避在真机上尚未验证。

## 既有真机经验

当前经验来自macOS、Docker和一台PW3，不能扩展为所有设备兼容。

| 范围 | 已取得的证据 | 尚不能宣称 |
| --- | --- | --- |
| 额度与服务 | 真实Codex标准额度、LAN中文PNG；Claude使用无额度fallback | Claude真实额度正确性 |
| 安装与画面 | Scriptlet/FBInk绘图及用户视觉确认；缓存、固定占位和早醒修复已USB部署并SHA256核验 | 所有固件/型号的显示、方向和残影表现 |
| RTC循环 | 既有短期自动返回记录；最近会话4次frame_ok跨18分21秒，无收到stopped；用户确认超过原故障窗口仍为额度图 | 每轮成功联网、所有RTC返回或连续一小时稳定性；该会话仅收到一次resumed且存在回报空白 |
| 提前唤醒 | 2026-10-11设备日志记录了“早醒后20秒重新挂起”导致操作中途失去响应；改为早醒即停止后有离线回归覆盖 | 早醒即停止在真机上的表现 |
| 换网与重连 | 曾恢复新网访问；Wi-Fi未连接后恢复并刷新 | 所有DHCP/换网场景自动恢复；新版有界就绪/已知地址重试仍需实际AP验证 |

全屏刷新残影、停止状态恢复、实际功耗、长时间稳定性、不同固件及其他型号仍须单独验收。启动被遗留锁拒绝的恢复手顺见[runbook](runbook.md)。

新用户按[手顺](runbook.md)使用自己的环境并填写[验收模板](acceptance-record.md)。个人部署摘要、最近安装报告、有限验收证据和必要回滚备份留在忽略的docs/local及runtime，不随源码公开；通用行为以Spec和技术设计为准。
