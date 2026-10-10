#!/bin/sh
# Name: 重找额度服务器
# Author: Kindle Quota Display
# DontUseFBInk
BASE=/mnt/us/eink-dashboard
# The active worker owns Wi-Fi, RTC and drawing; otherwise perform one shot.
exec "$BASE/quota-dashboard.sh" rediscover > "$BASE/discovery.log" 2>&1
