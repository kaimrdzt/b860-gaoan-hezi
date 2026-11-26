# 05 · 常见问题排查

---

## 1. 坏包与回落 U-Boot

| 现象 | 原因 | 处理 |
|---|---|---|
| 烧完仍是 `Resetting CPU` 死循环 | 包内仍有有效 env，或 boot 未真正破坏 | 用“双腿全断”包：坏 boot + 无 env + 无 system |
| `boot system norm failed, try boot safe!` 后又启动成功 | system 项仍在，SAFE 腿成功 | 从包中删除 system item |
| 停在启动 logo 不动 | boot 分区内容未破坏干净 | 确认前 64 KiB 已清零，VERIFY 已重算 |
| 烧录工具报 `store ddr_parameter erase` | 设备在 U-Boot 从模式，不是冷 BootROM | 彻底断电重来 |
| 烧录工具校验失败 | VERIFY 或包头 CRC 没重算 | 用 `aml.py verify` 检查，重新组包 |
| 包大小异常（约 1GB） | 误把 system item 带进来了 | 检查 items 列表，确认无 system |

---

## 2. 命令探测

| 现象 | 原因 | 处理 |
|---|---|---|
| 所有命令都显示 `UNKNOWN` | 没进提示符，或串口没连对 | 先确认能看到 `gxl_p211_v1#`，回车有回显 |
| `help` 无任何输出 | 该 U-Boot 裁剪了 help 输出 | 正常现象，用 `if/echo` 探针 |
| `printenv name` 无输出 | 单变量查询被裁 | 裸 `printenv` 全量查看 |
| `md` 读不出内容 | 读输出被裁 | 用 `itest.l *addr == value` 判断 |
| 探针命令缺字符 | 发送太快 | 20 B / 25 ms 慢发 |
| `PB_NO_n` 大量出现 | 裸命令返回非 0（缺参数），不代表不存在 | 查 `docs/02` 的用法补参数 |
| 某条命令后串口无响应 | 命令阻塞（fastboot/update/loady） | 断电重上电，回到提示符 |

---

## 3. 启动与持久化

| 现象 | 原因 | 处理 |
|---|---|---|
| 停在 `gxl_p211_v1#`，无 `DSH_AUTOBOOT` | env 没生效 / 包里没 env | 检查包内 env item 与 CRC |
| `Bad Linux ARM64 Image magic` | 内核槽偏移或长度错 | 核对 `docs/03` 槽位表 |
| `Resetting CPU` | 误用 `booti`，或 `text_offset=0` | 必须走 trampoline + `go` |
| `Wrong Ramdisk Image Format` | initrd 长度/内容不对 | 重算 initrd 长度并更新 `storeargs` |
| 内核起来但无 shell | DTB `/chosen/bootargs` 缺 `initcall_blacklist` | 参数编进 DTB |
| `CPUs started in inconsistent modes` | trampoline 的 `spsr` 设置不对 | 使用已验证的 256 B trampoline |
| 重启后 HDMI 几何被压扁 | VPP 被按默认模式重置 | 运行 `restore_regs.sh` |
| 断电重启后进不去系统 | rootfs 被烧录擦除 | 重新推送 rootfs |

---

## 4. rootfs 推送

| 现象 | 原因 | 处理 |
|---|---|---|
| 推送后 `wc -c` 大小不符 | busybox `nc` 静默截断 | 分片 ≤256 MiB，脚本强制校验大小 |
| `nc | dd` 极慢 | busybox 管道行为 | 改两段式：`nc > /tmp/chunk` 再 `dd` |
| `mount` 失败 | 偏移不对或数据不完整 | `losetup -o 3221225472`；抽样校验 |
| `/mnt/r` 只读，mkdir 失败 | 挂载时用了 ro | `mount -o remount,rw /mnt/r` |
| 重启后 `/mnt/r` 为空 | init 未执行 loop 挂载 | 检查 initramfs 的 `/init` 与 rootfs 偏移 |

---

## 5. HDMI 出图

| 现象 | 原因 | 处理 |
|---|---|---|
| 黑屏无信号 | `init_display` 没建 HDMI 管线 | 确认含 `hdmitx hpd;vout output 1080p60hz` |
| 颜色偏紫/偏粉 | HDMI 输出 YCbCr | 加 `hdmitx output 1080p60hz,8bits,rgb` |
| 画面纵向压缩约 5 倍 | VPP 被 576cvbs 默认值重置 | `restore_regs.sh`，逐个小步写 |
| 一次写多个寄存器后整机挂死 | 中间态让硬件状态机死锁 | 断电重启；严格按脚本顺序逐个写 |
| 写 canvas LUT 挂死 | 保护区热写 | 禁止；canvas LUT 在这块板上是死路 |

---

## 6. 网络调试

| 现象 | 原因 | 处理 |
|---|---|---|
| telnet 连不上 | 网络没起 / telnetd 没起 | 串口看 `ip addr`，手动起 telnetd |
| nc:2323 无响应 | init 没拉起命令通道 | 串口手动 `nc -lk -p 2323 -e /bin/sh &` |
| SSH 连不上 | 未安装/未启动（未验证项） | 见 `docs/04` §2.3 |
| 文件传到一半卡住 | nc 单连接限制 | 分片，脚本校验大小 |

---

## 7. 紧急恢复

| 情况 | 恢复方式 |
|---|---|
| 提示符可进 | 重新烧入持久化包（冷 BootROM） |
| 完全无串口输出 | 冷 BootROM + 烧录原厂包或持久化包 |
| 寄存器乱写导致挂死 | 断电；串口可用后执行 `restore_regs.sh` |
| env 改坏 | 烧入含正确 env 的整包（裸写 `0x38000000` 无效） |
