#!/bin/sh
# gwctl.sh - HTTP 网关开关（设备侧）
#   gwctl.sh start | stop | restart | status
BASE=/mnt/r/b860
WWW=$BASE/www
PORT=${PORT:-8080}
BB=${BB:-$BASE/busybox_cgi}
LOG=$BASE/httpd.log

case "$1" in
  start)
    mkdir -p /run
    chmod +x "$WWW"/cgi-bin/* "$BASE"/wdpet.sh 2>/dev/null
    "$BB" httpd -p "$PORT" -h "$WWW" 2>>"$LOG"
    sleep 1
    if "$BB" wget -q -O /dev/null "http://127.0.0.1:$PORT/cgi-bin/state" 2>/dev/null; then
      echo "GATEWAY_UP port=$PORT"
    else
      echo "GATEWAY_FAIL"; tail -5 "$LOG" 2>/dev/null
    fi
    # 开机自动恢复显示（1080p 几何 + 显示修正），后台延迟 2 秒执行
    if [ -f "$BASE/restore_regs.sh" ]; then
      ( sleep 2; sh "$BASE/restore_regs.sh" >"$BASE/restore.log" 2>&1 & )
      echo "display restore scheduled"
    fi
    ;;
  stop)
    pkill -f "httpd -p $PORT" 2>/dev/null && echo STOPPED || echo NOT_RUNNING
    ;;
  restart)
    sh "$0" stop >/dev/null 2>&1
    sleep 1
    sh "$0" start
    ;;
  *)
    if "$BB" wget -q -O /dev/null "http://127.0.0.1:$PORT/cgi-bin/state" 2>/dev/null; then
      echo "GATEWAY_UP port=$PORT"
    else
      echo "GATEWAY_DOWN"
    fi
    ;;
esac
