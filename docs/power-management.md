# 电源与无线行为

## 省电循环

当前实现将RTC待机与关闭无线放在同一省电分支：

```text
下载并绘图 → 设置180秒alarm → wirelessEnable=0 → mem休眠
→ RTC返回 → 清除自身alarm → wirelessEnable=1 → 等8秒 → 再刷新
```

所以每轮Wi-Fi重新连接属于程序主动行为，网络正常也会发生。调用的是系统级无线开关；[Amazon Paperwhite手册](https://kindle.s3.amazonaws.com/UserGuide/Paperwhite_V2/Kindle_Paperwhite_V2_UserGuide_US.pdf)将关闭无线与飞行模式对应，因此界面可能出现飞行模式变化。各固件的图标/状态表现需真机确认，未测量该策略的具体功耗收益。

## 配置与启动

server.conf模板为ALLOW_SUSPEND=0；但bootstrap自检通过后将其改为1，正常主入口启用RTC。仅改配置为0后再点击主入口不能保持Wi-Fi常开。

直接运行dashboard的普通等待分支（ALLOW_SUSPEND=0）保持Wi-Fi开启，不写power/RTC sysfs，用于已有终端环境的诊断。主入口目前没有独立的常开模式选项；要增加此产品行为，应同步修改bootstrap策略、配置和验收。

仅删除关闭无线的语句而保留mem休眠，不能承诺Wi-Fi关联会保持，需验证驱动和固件。

## 恢复与限制

- 保存开始时可读的无线/屏保开关，退出或单次刷新结束后恢复。开始时无线关闭，则结束后再次关闭属于预期恢复。
- 不覆盖其他进程的wakealarm，使用可用rtc0/rtc1，兼容硬件与系统epoch不同。
- 提前返回的经过时间少于INTERVAL-30时退出，恢复阅读环境；该规则不能确定唤醒原因一定是电源键。
- 联网目前只固定等待8秒，没有关联/IP/health就绪检查。慢网络可能使本轮失败留旧图，下一轮重试。
- 设备自报resumed或frame_ok只能证明已记录的分支；一小时稳定性、full flash残影、停止恢复和耗电须另外验证。

二开保持Wi-Fi常开或优化重连时，使用[DEV](../DEV.md)中的反馈方法并更新[Spec](spec.md)。
