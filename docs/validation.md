# 验证范围与边界

## 离线检查

入口为 `sh scripts/offline-check.sh`。当前36项unittest覆盖标准化、白名单、源/窗口/时钟/数值异常、独立失败缓存、CLI超时/退出/1MiB上限、进程组清理、原子写入与锁、HTTP路由/缓存、PNG尺寸/灰阶、生成器输出限制、USB目标校验、CIDR发现和RTC模拟。

Shell行为测试使用假的HTTP/LIPC/FBInk/RTC，覆盖实际私有/22跨子段发现、/28边界、大网段/公网拒绝、旧IP失效、配置注入拒绝、坏PNG/解码失败留好缓存、单实例和状态恢复。

另外执行Shell语法检查、合成采集、五种中文预览。GitHub Actions运行同一离线入口，不要求真实账户、Kindle或项目凭据。CI首次运行是否通过应以GitHub上的结果为准。

| 合成预览 | 场景 |
| --- | --- |
| [正常](assets/preview.png) | 两个Provider各两窗口 |
| [失败缓存](assets/cached-error.png) | 采集失败保留旧数据 |
| [过期](assets/stale.png) | sampled_at超过新鲜度阈值 |
| [无数据](assets/unavailable.png) | 没有有效snapshot |
| [第三窗口](assets/third-window.png) | 三窗口布局、未知时间 |

所有公开预览和fixtures均为合成数据。离线结果不能宣称Provider接口或硬件已验收。

2026-10-08公开整理复验：按Git忽略规则导出的源码不带.env、runtime、build或docs/local，分别在macOS和使用现有Python/Pillow/Noto镜像的无网络Linux容器中运行同一离线入口，两处36项测试及Shell语法/合成预览均通过。依赖运行环境已预装，未宣称重新安装依赖或GitHub云端CI已执行。

## 既有真机经验

在macOS、Docker和一台PW3环境中已取得真实Codex标准额度、LAN中文PNG、Scriptlet安装与绘图、用户视觉确认，以及连续三次绘图/两次RTC自动返回的短期记录。未取得Claude真实额度，通用无额度fallback已使用。

长期观察曾因提前唤醒而结束，因此没有连续一小时通过结论；全屏刷新残影、停止/早醒恢复、实际功耗、不同固件和其他型号仍需各自验收。自动/手工更新设备配置后恢复新网访问不等同于未来所有DHCP自动发现已通过。

这些经验只用于说明适配基线。个人配置、原始设备日志、聊天和备份不随源码公开；新用户须按[手顺](runbook.md)使用自己的环境并填写[验收模板](acceptance-record.md)。
