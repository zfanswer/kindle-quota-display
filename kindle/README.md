# Kindle 客户端

完整功能说明见 [Kindle 脚本功能与使用说明](../docs/kindle-scripts.md)，包含五个 Library 入口、四个内部脚本、调用关系、配置和日志位置。

- `documents/`：四个日常入口，加一个临时恢复自检入口；安装到 `/mnt/us/documents/`。
- 当前目录的四个 `.sh`：内部实现；安装到 `/mnt/us/eink-dashboard/`。
- `server.conf.example`：配置模板，由生成器填入实际服务器信息。

安装与回滚见 [手顺](../docs/runbook.md)，验证边界见 [验证说明](../docs/validation.md)。
