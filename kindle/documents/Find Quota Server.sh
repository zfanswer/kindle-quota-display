#!/bin/sh
# Name: 重找额度服务器
# Author: Kindle Quota Display
BASE=/mnt/us/eink-dashboard
# This entry deliberately leaves the Scriptlet runner's on-screen output on:
# the search reports its progress there, and discovery.log keeps a copy. The
# active worker owns Wi-Fi, RTC and drawing; otherwise this performs one
# search and one refresh itself.
: > "$BASE/discovery.log"
{
    if "$BASE/quota-dashboard.sh" rediscover; then
        # The server answers again: resume the loop unless it is already running.
        /bin/sh "$BASE/bootstrap.sh"
    else
        # Leave the reason readable before the Library repaints.
        sleep 8
    fi
} 2>&1 | tee -a "$BASE/discovery.log"
