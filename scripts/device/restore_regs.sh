#!/bin/sh
# restore_regs.sh — 重启后把 VPP 恢复到 1080p 全屏参数
# 逐个写，每步读回验证，避免中间态挂死
W=/proc/vpuregs_write
M=/mnt/r/b860/mods

[ -e /proc/vpuregs ] || insmod $M/vpuregs.ko 2>/dev/null
sleep 0.5
[ -e "$W" ] || { echo "[!] no $W"; exit 1; }

put() {  # put <addr> <val> <name>
    echo "$1 0x$2" > $W
    sleep 0.15
    got=$(grep "^$3 " /proc/vpuregs | sed 's/.*val=//')
    if [ "$got" = "0x$2" ]; then
        echo "  [ok] $3 = $got"
    else
        echo "  [!] $3 = $got (want 0x$2)"
    fi
}

echo "[restore] VPP 1080p"
put 0x7700 02000000 VPP_OSD_VSC_PHASE_STEP
put 0x772c 00000b40 VPP_OSD_SCO_V_START_END
put 0x7728 00000eff VPP_OSD_SCO_H_START_END
put 0x770c 01000000 VPP_OSD_HSC_PHASE_STEP
echo "[restore] done"
