# 依赖与设计来源

外部项目分别维护自己的源码、许可和安装要求；本库不包含这些项目的二进制或源码副本。

| 来源 | 用途 |
| --- | --- |
| [CodexBar](https://github.com/steipete/CodexBar) / [CLI文档](https://github.com/steipete/CodexBar/blob/main/docs/cli.md) | 宿主机额度采集与认证管理；本库只调用CLI和标准化结果 |
| [v0.72.0 CLIHelp](https://github.com/steipete/CodexBar/blob/v0.72.0/Sources/CodexBarCLI/CLIHelp.swift) / [CLIPayloads](https://github.com/steipete/CodexBar/blob/v0.72.0/Sources/CodexBarCLI/CLIPayloads.swift) / [UsageFetcher](https://github.com/steipete/CodexBar/blob/v0.72.0/Sources/CodexBarCore/UsageFetcher.swift) | 初始适配参考：OAuth来源、usage窗口、usedPercent、resetsAt、updatedAt、合成占位 |
| [KindleModding](https://kindlemodding.org/) / [Scriptlets](https://kindlemodding.org/kindle-dev/scriptlets.html) | 用户自行准备Jailbreak环境，documents入口metadata及安装/运行hooks |
| [FBInk](https://github.com/NiLuJe/FBInk) | 用户设备上安装的图片绘制工具，PNG支持由实际构建确认 |
| [remote-eink-dashboard](https://github.com/sep1107/remote-eink-dashboard/tree/2b12c968460ce94c5e2584c40efe02a8fd0ad14a) | Kindle联网、绘图、RTC待机流程的设计参考；本库为独立服务，不使用其镜像/服务契约 |
| [Pillow](https://github.com/python-pillow/Pillow) | 中文图片渲染与PNG生成 |
| [Debian Noto CJK文件清单](https://packages.debian.org/bookworm/all/fonts-noto-cjk/filelist) | Docker中NotoSansCJK字体路径和SC face选择 |
| [Amazon Paperwhite用户手册](https://kindle.s3.amazonaws.com/UserGuide/Paperwhite_V2/Kindle_Paperwhite_V2_UserGuide_US.pdf) | 无线关闭与飞行模式行为参考，各固件需自行验收 |

当前CodexBar版本可能改变CLI或字段；升级后重新核对source与payload，不能通过放宽白名单或保存原始凭据绕过兼容问题。公开fixtures按结构人工编写，非真实账户响应。

项目许可证为[Apache-2.0](../../LICENSE)，完整版来自[Apache官方](https://www.apache.org/licenses/LICENSE-2.0.txt)。构建时下载的Python、Pillow、字体及系统包使用各自许可。
