# Contributing

请先阅读 [DEV.md](DEV.md) 和 [行为 Spec](docs/spec.md)。小范围修复可直接提交 PR；新增 Provider、设备型号、认证机制或电源模式，先说明所改变的契约和设备验证方法。

1. 在分支中修改代码，使用合成 fixture 复现问题。
2. 执行 `sh scripts/offline-check.sh`，补充与问题相关的测试。
3. 更新受影响的文档。涉及 Kindle 的改动说明固件、FBInk、Scriptlet 环境及是否真实部署测试。
4. PR 描述写清触发条件、最终行为、验证结果和未验证边界。

提交中不要包含 `.env`、真实 quota JSON、设备日志/备份、生成安装包、聊天记录或认证数据。Bug 报告使用固定 `error_code` 和脱敏后的环境信息，不贴原始 CodexBar 输出。

贡献按仓库的 [Apache-2.0 许可证](LICENSE)提交。上游依赖有各自的许可证，新增或复制第三方内容时保留来源和许可声明。
