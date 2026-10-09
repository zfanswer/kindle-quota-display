#!/bin/sh
# Name: 开启Agent额度
# Author: Kindle Quota Display
# DontUseFBInk
# UseHooks
on_install() {
    # The installed Scriptlet integration calls this after indexing the new file.
    (sleep 10; /bin/sh /mnt/us/eink-dashboard/bootstrap.sh > /mnt/us/eink-dashboard/bootstrap.log 2>&1) &
}
on_run() {
    /bin/sh /mnt/us/eink-dashboard/bootstrap.sh > /mnt/us/eink-dashboard/bootstrap.log 2>&1
}
