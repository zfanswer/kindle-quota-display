# GitHub发布说明

## 文件边界

公开源码包括Python/Shell、默认配置与示例、tests合成fixtures、Schema、通用文档、合成预览、Apache-2.0 LICENSE/NOTICE和CI。

下列为忽略的本地内容，不上传：

- `.env`及变体（保留公开`.env.example`）、credentials/secrets、实际server.conf/server.cache、`*.local.*`配置。
- runtime中的真实quota、日志、事件、设备备份；build/dist中的安装包、plist、诊断和输出。
- docs/local中的本地部署摘要、个人路径/IP、安装及验收记录；个人验收也可另存docs/acceptance.local.md。
- 虚拟环境、Python缓存、OS/编辑器文件、本地Agent/CodeGraph数据。

不要为发布而删除仍在使用的.env、runtime或设备备份，忽略即可。Docker构建上下文采用白名单，只包含Dockerfile、requirements.txt和quota_display源码。

临时诊断脚本、重复源码副本、旧生成包和测试输出可在工作完成后清理。正式tests/fixtures是可重复验证的一部分；本地保留最近安装报告、必要验收证据及回滚备份，公开验证文档描述当前结果与边界，不堆积逐次排查流水。

## 首次提交前

若下载的是ZIP而非Git clone，先在项目根目录执行 `git init -b main`。检查：

```sh
git status --short --untracked-files=all
git status --short --ignored
git check-ignore .env runtime/quota.json build/kindle-install docs/local/
sh scripts/offline-check.sh
```

gitignore只对未跟踪文件生效。若旧版本已经跟踪个人文件，用git rm --cached取消跟踪而不删本地文件；若敏感内容已经进入历史，需要另外处理历史，不能只加ignore后宣称已移除。

首次暂存和审查可执行：

```sh
git add .
git diff --cached --stat
git diff --cached
git ls-files
```

核对没有个人主机名、绝对用户目录、真实quota/账户标识、token/cookie、聊天存档或设备备份。不要用git add -f绕过本项目忽略规则；公开截图仅使用合成数据。

Apache-2.0 LICENSE与NOTICE随源码提交。GitHub仓库名、所有者、remote和公开可见性由发布者选择；使用GitHub页面或gh创建远端后再按其指引提交/push。本手顺不会创建远端、上传或替你选择账号。

## 发布验证

- 从待发布文件重新导出/clone到干净目录，不带.env/runtime/build/docs/local，执行离线检查。
- 确认README依赖前提、脚本说明、DEV handoff和文档链接可读，示例用通用值。
- GitHub Actions第一次实际运行后再报告CI通过；本地检查不能替代云端结果。
- 设备兼容表只填写真正验收过的型号/固件，不把mock、短期循环或第三方项目成功扩展为所有设备可用。
