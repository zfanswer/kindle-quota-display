# 安装、验证与回滚手顺

前提见[README](../README.md)。本手顺假定你已经准备好Jailbreak、Scriptlets、FBInk、CodexBar CLI和账户登录；不安装这些组件，也不迁移凭据。设备行为见[脚本说明](kindle-scripts.md)及[电源行为](power-management.md)。

## 1. 离线基线

在项目根目录准备Python环境；macOS有可用系统中文字体，Linux安装Noto CJK或指定字体路径。

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
sh scripts/offline-check.sh
```

离线fixture只写build/preview，不能复制为runtime的真实额度。确认生成的五种合成预览中文正常、布局无溢出。

## 2. 宿主机真实采集

```sh
codexbar --version
mkdir -p runtime
python -m quota_display.collector --cli "$(command -v codexbar)"
```

只保存标准化runtime/quota.json。检查每源status、sampled_at、remaining_percent和reset_at，与CodexBar相同账户对照。至少一个目标源正常即可开始显示；未取得额度的源验证暂无数据fallback。任意源失败时退出1，但完整snapshot仍写入。

认证/Keychain提示由账户所有者通过CodexBar或Provider既有登录流程处理，不导出Auth、token、cookie或原始usage JSON。账户切换时先停采集任务，将旧runtime/quota.json移到忽略的本地备份，再采集，避免跨账户使用旧额度。

## 3. 图片服务与LAN

```sh
[ -f .env ] || cp .env.example .env
docker compose config
docker compose up -d --build
docker compose ps
curl --fail http://127.0.0.1:8486/healthz
```

期望health为两行：

```text
EINK_QUOTA_V1
SERVER_ID=kqd-pw3
```

打开http://127.0.0.1:8486/frame/kindle1.png，检查1072×1448、中文、各卡片更新时间/窗口/剩余/固定重置时刻。容器安装Noto CJK，Kindle不需要字体。health仅表示进程可用，不表示额度采集成功。

Kindle访问前，找出与其同网的宿主机IPv4和主机名。macOS可查询：

```sh
route -n get default
ipconfig getifaddr en0
scutil --get LocalHostName
```

en0只是常见Wi-Fi接口，按实际网络接口替换。在.env将QUOTA_BIND_ADDRESS设为LAN IPv4，或在可信网络设0.0.0.0，再运行docker compose up -d。全接口绑定便于换Wi-Fi，但所有可达接口上的设备可读取无认证额度/诊断；不做公网端口转发。

用另一设备访问`http://你的LAN地址:8486/healthz`。失败时检查绑定、防火墙和AP隔离，不默认关闭系统防火墙。QUOTA_SERVER_ID必须与Kindle配置一致，它不是认证密钥。

## 4. macOS定时采集

确认虚拟环境与CLI路径会长期保留。下面生成使用当前解释器绝对路径的plist，不安装：

```sh
python scripts/prepare.py launchd \
  --python "$(python -c 'import sys; print(sys.executable)')" \
  --cli "$(command -v codexbar)"
plutil -lint build/com.eink-quota.collector.plist
```

核对ProgramArguments、WorkingDirectory和日志路径，再安装：

```sh
mkdir -p "$HOME/Library/LaunchAgents"
cp build/com.eink-quota.collector.plist "$HOME/Library/LaunchAgents/"
launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.eink-quota.collector.plist"
launchctl kickstart "gui/$(id -u)/com.eink-quota.collector"
launchctl print "gui/$(id -u)/com.eink-quota.collector"
```

已存在同名job时先bootout旧job，再bootstrap；不要重复安装。观察至少三轮attempted_at推进、没有重叠。每源失败不阻止下一次180秒调度；StartInterval不保证严格实时或宿主机休眠时执行。移动仓库/删除虚拟环境后需重新生成plist。

Linux需自行配置systemd timer/cron，保留每次单次调用、绝对路径和防重叠行为；本库未提供或验证Linux定时部署。

## 5. 生成Kindle包

替换下面的示例IP/主机名；输出目录必须是新的项目子目录。

```sh
python scripts/prepare.py kindle \
  --server 192.168.1.50 \
  --host quota-host.local \
  --server-id kqd-pw3 \
  --output build/kindle-install
```

检查eink-dashboard/server.conf中的FBINK路径、端口/身份、间隔、FULL_REFRESH和休眠开关。默认FBINK为/mnt/us/libkh/bin/fbink。生成器拒绝覆盖现有包，重建时使用新目录。

包内有四个内部脚本、配置、五个Library入口及固定bootstrap-frame.png，manifest包含占位图SHA256。占位图仅显示“正在刷新quota信息”，无有效缓存时使用；旧版同名额度快照缺少标记会被忽略。更新时将固定图和脚本一起部署，不能只复制旧额度截图作为占位图。

**安装钩子可能在首次索引入口后自动自检并启用RTC循环。** 点击主入口也会自检后将ALLOW_SUSPEND改为1；不要把模板中的0理解为正常启动后一定不休眠。事先确认RTC/sysfs能力、无其他dashboard占用alarm，以及停止方法。

## 6. USB安装与推出

先点击“停止 Agent 额度”退出设备旧循环，再连接USB。macOS核对挂载点：

```sh
diskutil info /Volumes/Kindle
python scripts/install-kindle.py --bundle build/kindle-install --mount /Volumes/Kindle
```

上面仅核验。确认目标为Kindle卷及本项目目录后执行：

```sh
python scripts/install-kindle.py --bundle build/kindle-install --mount /Volumes/Kindle --apply
```

首次安装用上面的命令。已有项目必须用增量更新：

```sh
python scripts/install-kindle.py --bundle build/kindle-install --mount /Volumes/Kindle --update --apply
```

--update只替换4个内部脚本、固定图及4个永久入口，共9个文件；server.conf/server.cache保留，临时Recover入口不重新添加。安装器先备份将被替换的文件到唯一runtime/backups/kindle-时间戳目录，再逐文件原子替换并核验SHA256；installation.json记录替换清单与保留配置的hash。USB更新不是整包事务，须先停止旧任务。不会替换FBInk、Hotfix或个人文档。Linux须按实际挂载点手工备份/复制并校验；macOS安装器依赖diskutil，不适用于Linux。

正常安全推出整盘设备（用diskutil info确认实际整盘编号，勿照抄旧编号）或通过Finder推出。若被系统拒绝，停止占用并重新安全推出；不用强制卸载。退出USB模式后确认Kindle与宿主机同Wi-Fi。

## 7. 绘图、自动循环与停止

- 点击“刷新 Agent 额度”做单次刷新；已有循环持锁时拒绝并发，先停止再测试。
- 点击“开启Agent额度”先显示最近成功缓存，无有效缓存时显示固定刷新占位，再做设备能力检查并启动；已有循环只恢复画面。占位图不含额度/时间，不作为成功数据缓存；坏缓存或占位图不阻塞联网。
- 观察在线frame_ok、suspend_armed及后续frame_ok；resumed通常仅写Kindle本地日志；肉眼核对方向、中文、数据和残影。
- 点击“停止 Agent 额度”退出，确认Wi-Fi/屏保恢复并可正常阅读；电源键/其他提前唤醒不停止循环，保持无线关闭，短交互后以剩余RTC等待继续。

在已有设备终端中可检查：

```sh
/mnt/us/eink-dashboard/quota-dashboard.sh status
cat /mnt/us/eink-dashboard/server.cache
cat /mnt/us/eink-dashboard/run.log
cat /mnt/us/eink-dashboard/lifecycle.log
cat /mnt/us/eink-dashboard/power.log
```

不为调试临时安装SSH。USB可回读eink-dashboard持久日志；/tmp/kindle-quota-display是设备临时状态。发现失败用discovery.log，启动自检用bootstrap.log。lifecycle.log记录固定事件和系统epoch，不依赖服务器可达，达到256KiB时轮换为lifecycle.previous.log。resumed/early_wake表示提前返回且继续任务；stopped才表示退出。power.log记录每轮失败计数和下一间隔。离线、返回和停止事件通常只写本地，不因回报重新打开无线。

观察工具只读服务器事件：

```sh
python scripts/observe-kindle.py --url http://127.0.0.1:8486 \
  --minutes 70 --cycles 20 --min-duration 3600
```

新版观察工具只计算启动观察后的当前会话frame_ok数量和跨度，不再要求在线resumed，也不跨重启拼接。summary为passed表示收到足够帧回报（evidence=received_frames）；实际RTC需结合设备本地lifecycle.log核对；device_stopped、timeout、not_seen不算通过。事件是无认证自报，不能证明肉眼显示、实际功耗或full flash残影。

## 8. 故障与换网验收

按[模板](acceptance-record.md)建立本地记录，至少验证：

1. Mac服务离线时保留旧图，观察失败后RTC间隔3→6→9→12→15分钟；已知地址恢复后最多额外等待15分钟，成功清零。collector停止但HTTP在线时，10分钟后生成过期状态；旧离线PNG不能自行改字。
2. DHCP变化或换Wi-Fi后，主机名有效时可自动恢复；否则点击“重找额度服务器”，后台永不扫描。固定Host绑定需更新，0.0.0.0不需要。
3. 手工“重找额度服务器”跳过缓存、保存新地址并尝试刷新；已有循环活动时通过请求跳过退避并立即尝试刷新。
4. /21及更大网段、/31、/32或公网不自动扫描，通过固定IP/主机名配置；mDNS和AP隔离需环境验证。
5. 至少一小时连续自动循环、30分钟full refresh、停止恢复和提前唤醒继续刷新。提前唤醒后应有后续frame_ok，无stopped；实际退出后不能将两段会话累加成一次不中断成功。

30秒网络窗口与IPv4/已知地址短重试需要按实际AP验证，详情见[电源行为](power-management.md)。锁存在但无活动进程时，先核对status/PID，确认无refresh/run再处理遗留锁，不能删除活动锁。

若启动自检立即失败且bootstrap.log写着`Lock exists`，说明生命周期锁占用。没有设备终端可核对进程时，正常安全退出USB后通过Kindle系统菜单重启，再点击“开启Agent额度”；重启清除旧进程和/tmp临时锁，也可能清除成功图片缓存，随后使用固定刷新占位图。不要仅凭没有新的服务器回报就删除锁。

## 9. 停止与回滚

先在Kindle停止循环，核验原状态恢复，再停止宿主机采集与服务：

```sh
launchctl bootout "gui/$(id -u)/com.eink-quota.collector"
docker compose down
```

删除本项目LaunchAgent前保留配置；USB连接后备份当前项目配置/缓存，恢复runtime中的项目备份，或移走本项目四个永久入口、仍存在的临时恢复入口与eink-dashboard目录。不要清理其他documents、libkh或系统组件。runtime/.env保存个人状态，不作为源码提交。
