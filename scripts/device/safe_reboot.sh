#!/bin/sh
# safe_reboot.sh [timeout] — 用硬件看门狗强制复位，不依赖 reboot 系统调用
# 用法: sh safe_reboot.sh 5    (5 秒后硬件复位)
T=${1:-5}
W=/sys/class/watchdog/watchdog0

sync
if [ ! -e "$W" ]; then
    echo "[!] no $W, fallback to reboot -f"
    sync
    reboot -f
    exit 1
fi

echo "$T" > "$W/timeout" 2>/dev/null
echo "watchdog timeout set to $(cat $W/timeout 2>/dev/null)"

# 打开设备即启动看门狗，之后不喂狗 -> 超时硬件复位
exec 3> /dev/watchdog0
echo "[ok] watchdog armed ${T}s, not feeding -> hardware reset"

# 保持 fd 打开，什么都不做
i=0
while [ $i -lt $((T + 15)) ]; do
    sleep 1
    i=$((i + 1))
done
echo "[!] watchdog did not fire, fallback reboot -f"
sync
reboot -f
