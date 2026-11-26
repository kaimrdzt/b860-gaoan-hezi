# 06 · 端到端检查清单

> 从零开始复现的完整顺序。每一步都有明确的通过条件，不通过不要进入下一步。

---

## 阶段 0 · 环境准备

| # | 检查项 | 通过条件 |
|---|---|---|
| 0.1 | 串口线连接 | 设备管理器能看到 CH340 的 COM 号 |
| 0.2 | 串口参数 | 115200 8N1，DTR/RTS 置位 |
| 0.3 | 关闭占用程序 | MobaXterm / PuTTY / 串口助手全部退出 |
| 0.4 | 网线 | PC 与盒子同网段，能互相 ping 通 |
| 0.5 | 烧录工具 | 已安装，能识别 USB 设备 |
| 0.6 | 源文件 | 源包、原版 boot 分区内容、env blob、rootfs 镜像齐备 |

---

## 阶段 1 · 制作并烧入坏包，拿到提示符

| # | 操作 | 通过条件 |
|---|---|---|
| 1.1 | 生成双腿全断包 `build_prompt_package.py` | 脚本输出无 env、无 system、校验全过 |
| 1.2 | 彻底断电 → 接 USB → 上电 | 烧录工具识别为冷 BootROM |
| 1.3 | 烧入坏包 | 工具无报错，`store ddr_parameter erase` 未出现 |
| 1.4 | 上电看串口 | `boot system norm failed, try boot safe!` → `gxl_p211_v1#` |
| 1.5 | 执行证据 | `if echo CHAN_$((6*7))_OK; then echo PROBE_OK; fi` 回显两个标记 |

> 1.5 不通过，后面全部无效。

---

## 阶段 2 · 命令探索

| # | 操作 | 通过条件 |
|---|---|---|
| 2.1 | 运行 `probe_uboot_cmds.ps1` | 产出 `out\probe\probe-*.log` |
| 2.2 | 查看汇总 | `OK` 数量与 [02 清单](02-command-audit.md) 基线一致 |
| 2.3 | 复核 `UNKNOWN` | 每个都有“存在/不存在/未判定”的结论 |
| 2.4 | 手动补测 | `setenv`/`saveenv` 等有副作用命令已单独确认 |
| 2.5 | 归档 | 日志路径与结果写入记录 |

---

## 阶段 3 · 生成持久化包

| # | 操作 | 通过条件 |
|---|---|---|
| 3.1 | 确认四个槽位长度 | 与 Image/DTB/initrd/trampoline 实际大小一致 |
| 3.2 | 确认 env | `init_display` 含 `hdmitx output ... ,8bits,rgb`；`storeargs` 链完整 |
| 3.3 | 运行 `build_persist_package.py` | 仅 env item 变化，其余与源包逐字节一致 |
| 3.4 | 包校验 | `aml.py verify` 全部 PASS |

---

## 阶段 4 · 烧入持久化包

| # | 操作 | 通过条件 |
|---|---|---|
| 4.1 | 冷 BootROM 烧录 | 同 1.2/1.3 |
| 4.2 | 上电 | 1–2 秒 HDMI 出现 logo |
| 4.3 | 串口 | `HDMIINIT_MARKER` → `DSH_AUTOBOOT` → `Linux version` |
| 4.4 | 内核完成 | `Freeing unused kernel memory` |
| 4.5 | shell | 出现设备提示符 |

---

## 阶段 5 · 推送 rootfs

| # | 操作 | 通过条件 |
|---|---|---|
| 5.1 | 设置 `B860_HOST` / `B860_ROOTFS_IMG` | 地址与文件正确 |
| 5.2 | 全量推送 | 10 片全部 `DD_RC=0` |
| 5.3 | 单片校验 | `--verify` 首/中/尾抽样 PASS |
| 5.4 | 挂载 | `mount` 出现 `/dev/loop0 on /mnt/r type ext4 (rw)` |
| 5.5 | 部署设备脚本 | `gwctl.sh start` 返回 `GATEWAY_UP` |
| 5.6 | 几何恢复 | `restore.log` 四项 `[ok]` |

---

## 阶段 6 · 掉电持久化验证

| # | 操作 | 通过条件 |
|---|---|---|
| 6.1 | 直接拔电源 | 设备完全断电 |
| 6.2 | 重新上电，零输入 | 不碰键盘、不接串口输入 |
| 6.3 | 串口五层断言 | `GXLX2:BL1` → `DSH_AUTOBOOT` → `Linux version` → `Freeing unused kernel` → 提示符 |
| 6.4 | 区分软复位 | 日志无 `resetting ...`、无 PSCI Affinity Map |
| 6.5 | 数据保留 | `/mnt/r` 自定义文件仍在 |

---

## 阶段 7 · HDMI 验证

| # | 操作 | 通过条件 |
|---|---|---|
| 7.1 | 启动 logo | 上电 1–2 秒可见 |
| 7.2 | 色彩 | 纯色测试无偏紫/偏粉（RGB 4:4:4） |
| 7.3 | 几何 | 画面无纵向压缩，`restore_regs.sh` 四项 `[ok]` |
| 7.4 | 重启后复测 | 几何仍正确（gwctl 自动调度） |

---

## 阶段 8 · 网络调试

| # | 操作 | 通过条件 |
|---|---|---|
| 8.1 | telnet | `telnet <盒子IP>` 能登录 |
| 8.2 | nc 通道 | `dev.py` 的 `alive()` 返回 True |
| 8.3 | HTTP | `/cgi-bin/state` 返回 200 |
| 8.4 | SSH（可选、未验证） | 按 [04 §2.3](04-kernel-build-network.md) 集成后自行验证 |

---

## 失败回退

| 卡点 | 回退动作 |
|---|---|
| 进不了提示符 | 检查包是否真的无 env/system；确认冷 BootROM 模式 |
| 持久化包不启动 | 回到坏包进提示符，核对槽位长度与 env |
| rootfs 挂载失败 | 重新推送，确认偏移 3072 MiB |
| 掉电后不自启 | 检查 env item 是否随包写入、CRC 是否正确 |
| 画面异常 | 先跑 `restore_regs.sh`，再检查 `init_display` |
