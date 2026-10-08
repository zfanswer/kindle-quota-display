#!/bin/sh
# Name: 重找额度服务器
# Author: Kindle Quota Display
# DontUseFBInk
BASE=/mnt/us/eink-dashboard
# Persist a bounded last result because the Library may hide script stdout.
if host=$("$BASE/find-server.sh" --force 2> "$BASE/discovery.log"); then
    printf 'FOUND %s\n' "$host" > "$BASE/discovery.log"
    # Make a successful manual rediscovery visible with the current quota image.
    exec "$BASE/quota-dashboard.sh" refresh
fi
exit 1
