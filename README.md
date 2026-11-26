# B860 高安盒子 · 坏包回落 U-Boot、命令探索与 Linux 持久化

> 面向 **高安盒子**（Secure Boot 开启、精简命令版 U-Boot）的复现工程。
> 解决三个实际问题：
> 1. **原厂 U-Boot 无法打断** → 制作“坏的刷机包”，刷入后让盒子自动回落 U-Boot 提示符
> 2. **不知道该 U-Boot 有哪些命令可用** → 用探针脚本批量探测并输出清单
> 3. **如何把 Linux 刷进去并掉电自启** → 裸分区读 + trampoline + 持久化 env

---

## 1. 设备标注

| 项目 | 值 |
|---|---|
| 原文标注 | **精**（精简命令版 U-Boot） |
| 整机 | ZTE ZXV10 B860AV2.1-T **高安版**（Secure Boot 开启） |
| 安全等级 | BL31 打印 `GXL secure boot!`；boot/recovery 内核为 AES 加密 + RSA-2048 签名 |
| SoC | Amlogic S905L3-B（GXLX2，`aml_dt=gxlx2_p295_1g`，Platform ID `0x0811`） |
| CPU | 4× Cortex-A53，BL2 固定 1200MHz |
| GPU | ARM Mali-450 |
| 内存 | 1 GiB DDR4 |
| 存储 | 8 GB eMMC（实际可用约 7.22 GiB，`mmcblk2` 整盘无分区表） |
| 网络 | 100M 内置 PHY（RMII） |
| 显示 | HDMI，最高 1080p60 |
| 串口 | `ttyAML0` / U-Boot 控制台，115200 8N1 |
| 固件特征 | U-Boot 输出路径被裁剪（`help` / `md` / `printenv <name>` 无回显）；Secure Boot 开启 |

> “精”是原文对设备的标注，指**精简命令版 U-Boot**，不是型号。表中其余字段来自本机实测
> （引导日志、DTB 反编译、分区表解析），不是推测。

> 如果你的设备不是高安版（BL31 不打印 `secure boot`）、或 U-Boot 命令完整，
> 本文的坏包回落路径与命令清单**不保证适用**。

---

## 2. 两个核心问题

### 2.1 原厂 U-Boot 无法打断

正常启动时没有可用的打断窗口，按键和串口输入都进不去，因此拿不到控制台。
`bootsys` 内部走 `imgread kernel boot`，会做 AES 解密 + RSA-2048 验签，自编明文内核无法直接启动。

**解决思路**：不攻击签名，而是让 `bootsys` 的两条启动腿同时失败，U-Boot 会主动停下来进提示符。

```
NORM 腿 → 读 boot 分区     ┐
                            ├─ 同时切断 → boot system norm failed, try boot safe!
SAFE 腿 → 读 system/loader ┘            → gxl_p211_v1#   ✅ 拿到控制台
```

具体做法见 [docs/01-bad-package-fallback.md](docs/01-bad-package-fallback.md)。

> ⚠️ 只坏内核、保留 env 的包会进入 `Resetting CPU` 死循环，**不会**回落提示符。
> 必须“坏 boot + 无 env + 无 system”三件套同时满足，这是实机验证过的唯一有效组合。

### 2.2 精简版 U-Boot 的命令不透明

该 U-Boot 的输出路径被大面积裁剪：`help`、`md`、`printenv <name>` 等命令**存在但无回显**，
“无输出”不等于“命令不存在”。直接靠 `help` 列表会严重漏判。

**解决办法**：hush 的 `echo` 通道仍然可用，用探针表达式绕开被裁的输出：

```sh
if <cmd>; then echo PB_OK_n; else echo PB_NO_n; fi
```

`scripts/probe/probe_uboot_cmds.ps1` 会自动遍历安全命令并汇总 `OK / NO / UNKNOWN`。
完整命令清单（含用法、危险命令、绕过输出裁剪的技巧）见
[docs/02-command-audit.md](docs/02-command-audit.md)。

---

## 3. 仓库结构

```
b860-高安盒子/
├── README.md
├── LICENSE
├── docs/
│   ├── 01-bad-package-fallback.md   坏包制作 + 自动回落 U-Boot（含失败反例）
│   ├── 02-command-audit.md          探针方法 + 逐步操作 + 完整命令清单
│   ├── 03-flash-linux-persist.md    刷 Linux 到 eMMC + 掉电自启
│   ├── 04-kernel-build-network.md   内核编译 + 串口/网络调试
│   ├── 05-troubleshooting.md        常见问题排查
│   └── 06-end-to-end-checklist.md   端到端检查清单（8 阶段）
├── scripts/
│   ├── build/
│   │   ├── aml.py                    AML v2 包解析 / 校验 / 组装
│   │   ├── build_prompt_package.py   双腿全断坏包（回落提示符，推荐）
│   │   ├── build_bad_boot_package.py 单腿坏包（只坏内核，反例留档）
│   │   ├── build_ubootshell.py       好内核 + 无 env/system 的提示符包
│   │   └── build_persist_package.py  持久化启动包（修正 env）
│   ├── probe/
│   │   ├── probe_uboot_cmds.ps1      批量探针
│   │   └── uboot_cmd.ps1             在提示符逐条发命令
│   ├── flash/
│   │   └── check_burnmode.ps1        判定冷 BootROM / U-Boot 从模式
│   ├── deploy/
│   │   ├── dev.py                    设备网络命令通道
│   │   └── push_rootfs.py            rootfs 分片推送
│   ├── device/
│   │   ├── restore_regs.sh           恢复 1080p 几何
│   │   ├── gwctl.sh                  HTTP 网关（开机调度 restore）
│   │   └── safe_reboot.sh            看门狗硬复位
│   └── display_model.py              显示几何模型 + 自测
└── templates/
    └── v4_spec.reference.json        持久化包 item 结构参考
```

---

## 4. 脚本清单

| 脚本 | 用途 | 关键环境变量 / 参数 |
|---|---|---|
| `build/build_prompt_package.py` | 制作回落提示符的坏包 | `B860_V3_IMG`、`B860_V3_KERNEL`、`B860_PROMPT_IMG` |
| `build/build_bad_boot_package.py` | 单腿坏包（只坏内核，反例；`--restore` 可恢复 boot 分区） | 同上，输出 `B860_RESCUE_IMG` |
| `build/build_persist_package.py` | 持久化启动包（RGB/1080p env） | `B860_V3_IMG`、`B860_ENV_V3`、`B860_V4_IMG` |
| `build/build_ubootshell.py` | 好内核 + 无 env/system 的提示符包 | `B860_V3_IMG`、`B860_V3_KERNEL`、`B860_UBOOTSHELL_IMG` |
| `build/aml.py` | 包解析/校验/组装 | `python aml.py info\|verify\|extract\|build` |
| `probe/probe_uboot_cmds.ps1` | 批量探测可用命令 | `-Port`、`-ProbeWaitMs`、`-ExtraCmds`、`-CmdFile` |
| `probe/uboot_cmd.ps1` | 提示符执行命令 | `-Cmds printenv` 等 |
| `flash/check_burnmode.ps1` | 判定烧录模式 | `-LogRoot`（烧录工具日志目录） |
| `deploy/push_rootfs.py` | 推送 rootfs 到 eMMC | `B860_HOST`、`B860_ROOTFS_IMG`、`--seg`、`--verify` |
| `deploy/dev.py` | 设备 TCP 命令通道 | `B860_HOST`、`B860_SHELL_PORT` |
| `display_model.py` | 几何模型自测 | `--selftest` |

---

## 5. 快速开始（按顺序）

### 第 1 步：拿到 U-Boot 提示符

```powershell
# 1) 用源包与内核生成“双腿全断”坏包
$env:B860_V3_IMG     = 'out/v3.img'
$env:B860_V3_KERNEL  = 'out/boot_v3_kernel.bin'
$env:B860_PROMPT_IMG = 'out/prompt.img'
python scripts\build\build_prompt_package.py

# 2) 冷 BootROM 模式烧入（彻底断电 → 接 USB → 上电 → 烧录）
# 3) 上电观察串口
#    预期：boot system norm failed, try boot safe! → gxl_p211_v1#
```

### 第 2 步：探索可用命令

先验证串口执行证据，再跑批量探针：

```powershell
# 2.1 确认命令能真正执行（预期回显 CHAN_42_OK + PROBE_OK）
pwsh -NoProfile -File scripts\probe\uboot_cmd.ps1 -Port COM14 `
     -Cmds 'if echo CHAN_$((6*7))_OK; then echo PROBE_OK; fi'

# 2.2 批量探测安全命令（输出 OK / NO / UNKNOWN 汇总）
pwsh -NoProfile -File scripts\probe\probe_uboot_cmds.ps1 -Port COM14

# 2.3 追加自定义命令，或从文件批量读
pwsh -NoProfile -File scripts\probe\probe_uboot_cmds.ps1 -Port COM14 `
     -ExtraCmds 'help','bdinfo','iminfo'
pwsh -NoProfile -File scripts\probe\probe_uboot_cmds.ps1 -Port COM14 -CmdFile cmds.txt
```

日志在 `out\probe\probe-*.log`。
`UNKNOWN` 的复核方法、有副作用命令的手动补测流程、结果归档格式，见
[docs/02 §3 操作步骤](docs/02-command-audit.md#3-操作步骤逐步)。

### 第 3 步：刷入持久化 Linux 包

```bash
# 生成含正确 env 的持久化包（init_display + RGB + storeargs）
B860_V3_IMG=out/v3.img B860_ENV_V3=out/env_v3.bin B860_V4_IMG=out/persist.img \
  python3 scripts/build/build_persist_package.py
# 冷 BootROM 模式烧入 persist.img
```

### 第 4 步：推送 rootfs

```bash
export B860_HOST=192.0.2.100            # 示例地址，按实际修改
export B860_ROOTFS_IMG=/path/rootfs.img
python3 scripts/deploy/push_rootfs.py
```

### 第 5 步：掉电持久化验证

拔电 → 重新上电 → 串口应依次出现：

```
GXLX2:BL1 → DSH_AUTOBOOT → Linux version → Freeing unused kernel → B860AV2.1-T ~ #
```

中间不需要任何按键。详细判定方法见
[docs/03-flash-linux-persist.md](docs/03-flash-linux-persist.md)。

> 完整的分阶段检查表（8 个阶段、每步通过条件、失败回退）见
> [docs/06-end-to-end-checklist.md](docs/06-end-to-end-checklist.md)。

---

## 6. 关键参数速查

### 6.1 引导槽位（持久化包 system item 内）

| 载荷 | 包内偏移 | 长度 | 载入 DDR |
|---|---|---|---|
| Image | `0x38400000` | `0x0119B808` | `0x12000000` |
| DTB | `0x395C0000` | `0xA2A2` | `0x0F000000` |
| initrd | `0x39600000` | `0x1218A6` | `0x14000000` |
| trampoline | `0x39800000` | `0x100` | `0x0E000000` |

`storeargs` 链：

```
store read system 0x12000000 0x38400000 0x0119B808;
store read system 0x0F000000 0x395C0000 0xA2A2;
store read system 0x14000000 0x39600000 0x1218A6;
store read system 0x0E000000 0x39800000 0x100;
go 0x0E000000
```

### 6.2 rootfs

| 项 | 值 |
|---|---|
| 设备节点 | `/dev/mmcblk2`（整盘无分区表） |
| 偏移 | 3072 MiB（3 GiB） |
| 挂载 | `losetup -o 3221225472` + `mount -t ext4` |
| 推送分片 | 256 MiB × 10，两段式 nc |

### 6.3 env

| 项 | 值 |
|---|---|
| 大小 | 64 KiB |
| 格式 | `u32 CRC32` + `key=value\0...` |
| CRC 覆盖 | `blob[4:65536]` |
| 写入方式 | 烧录包内的 env item；或提示符上 `setenv` + `saveenv`。**裸写 `0x38000000` 无效** |

---

## 7. 风险提示

1. **刷机有变砖风险**：烧录工具会执行 `amlmmc erase 1`（约 108MB–7.22GB），
   rootfs 与自定义文件会丢失，必须提前备份。
2. **不要绕过烧录工具 dd 写 boot 分区**：绝对偏移未经实机证实。
3. **坏包只用于进入提示符**，不要长期当日常系统使用。
4. **危险命令会挂死或变砖**：`store erase/scrub/rom_write/mbr`、`efuse write`、
   `bootm <垃圾地址>`、`go <垃圾地址>`、`fastboot`、`update`（阻塞）。
5. **串口必须独占**，否则脚本打不开端口。
6. **高安签名未破解**：本文不替换 BL1/BL2/BL31/BL33，不伪造签名。

---

## 8. 待确认项

| # | 内容 | 现状 |
|---|---|---|
| 1 | 设备硬件细节 | 已按本机实测补充完整规格表；原文标注“精”保留并说明含义 |
| 2 | 源包（v3）的完整构建链 | 本仓库只含坏包/持久化包的增量脚本 |
| 3 | rootfs 镜像生成方法 | debootstrap 参数与软件源未记录 |
| 4 | 串口号 | 文档示例 COM14，按实际枚举修改 |
| 5 | 烧录工具版本 | 记录中出现多个版本，建议先用 2.2.4 |
| 6 | SSH 验证状态 | 现有记录只验证 telnet:23 / nc:2323 / HTTP:8080，SSH 未验证（见 docs/04） |
| 7 | v3/v4 镜像与 rootfs 分发 | 不含 1GB 级二进制，需自行准备 |
| 8 | 内核版本 | 记录中出现 6.12.115 与 7.x 两种产物；以源包内实际内核为准（`uname -r` 确认） |

---

## 9. 许可

脚本以 MIT 许可发布（见 [LICENSE](LICENSE)）。
不包含厂商固件、密钥或签名材料。
