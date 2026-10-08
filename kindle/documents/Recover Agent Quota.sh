#!/bin/sh
# Name: Agent 额度恢复自检
# Author: Kindle Quota Display
# DontUseFBInk
# UseHooks
on_install() {
    (sleep 10; /bin/sh /mnt/us/eink-dashboard/bootstrap.sh >> /mnt/us/eink-dashboard/bootstrap.log 2>&1) &
}
on_run() {
    /bin/sh /mnt/us/eink-dashboard/bootstrap.sh >> /mnt/us/eink-dashboard/bootstrap.log 2>&1
}
