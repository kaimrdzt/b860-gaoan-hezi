<a id="top"></a>

# B860 高安盒子 · 坏包回落 U-Boot、命令探索与 Linux 持久化 / B860 Gao'an Box: Bad-Package U-Boot Fallback, Command Discovery, and Linux Persistence

<p align="center"><a href="#english">English</a> | <a href="#chinese">中文</a></p>

<a id="chinese"></a>

## 中文版

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

## 9. 附件说明 / Releases and assets

**为什么没有任何附件上传？** 本项目只交付脚本、文档和模板等文本文件；此前没有创建任何 Release，
也没有向仓库上传固件镜像，所以 Releases 页面上看不到附件。这不是漏传，而是分发范围本来就不含 1GB 级二进制。

后续创建的 Release 附件是**仓库源码 ZIP**（仅含 README、docs、scripts、templates、LICENSE 等文本文件），
可在 [Releases（最新版）](https://github.com/kaimrdzt/b860-gaoan-hezi/releases/latest) 下载。

固件镜像、v3/v4 镜像与 rootfs **不随仓库或 Release 分发**，原因包括：

- **体积**：镜像为 1GB 级，Git/Release 不适合承载大体积二进制；
- **许可/版权**：厂商固件、内核二进制与相关组件不能在此重新分发；
- **脱敏**：镜像可能包含设备标识、密钥或签名材料，不适合公开上传。

因此需要自行准备合法来源的源包、内核与 rootfs，再按第 3、4 节生成和推送所需镜像。

[返回顶部](#top) · [English](#english)

---

## 10. 许可

脚本以 MIT 许可发布（见 [LICENSE](LICENSE)）。
不包含厂商固件、密钥或签名材料。

---

<a id="english"></a>

## English

> A reproduction project for the **Gao'an box** (Secure Boot enabled, U-Boot with a reduced command set).
> It addresses three practical problems:
> 1. **The stock U-Boot cannot be interrupted** → build a “bad firmware package” so the box falls back to the U-Boot prompt after flashing
> 2. **Unknown available U-Boot commands** → batch-probe them with scripts and export a list
> 3. **How to flash Linux and boot it after power loss** → raw-partition reads + trampoline + persistent env

---

## 1. Device identification

| Item | Value |
|---|---|
| Original annotation | **精** (reduced-command U-Boot) |
| Device | ZTE ZXV10 B860AV2.1-T **Gao'an edition** (Secure Boot enabled) |
| Security level | BL31 prints `GXL secure boot!`; boot/recovery kernels are AES-encrypted and RSA-2048 signed |
| SoC | Amlogic S905L3-B (GXLX2, `aml_dt=gxlx2_p295_1g`, Platform ID `0x0811`) |
| CPU | 4× Cortex-A53, BL2 fixed at 1200MHz |
| GPU | ARM Mali-450 |
| Memory | 1 GiB DDR4 |
| Storage | 8 GB eMMC (about 7.22 GiB usable; `mmcblk2` whole disk has no partition table) |
| Network | 100M internal PHY (RMII) |
| Display | HDMI, up to 1080p60 |
| Serial console | `ttyAML0` / U-Boot console, 115200 8N1 |
| Firmware traits | U-Boot output path is trimmed (`help` / `md` / `printenv <name>` produce no echo); Secure Boot enabled |

> “精” is the original annotation for the device and means **reduced-command U-Boot**, not a model number.
> All other fields come from on-device measurements (boot logs, DTB decompilation, partition table parsing), not guesses.

> If your device is not the Gao'an edition (BL31 does not print `secure boot`), or if its U-Boot command set is complete,
> the bad-package fallback path and command list in this document **are not guaranteed to apply**.

---

## 2. Two core problems

### 2.1 The stock U-Boot cannot be interrupted

There is no usable interrupt window during normal boot; key presses and serial input are ignored, so no console is available.
Internally, `bootsys` calls `imgread kernel boot`, which performs AES decryption and RSA-2048 signature verification;
a self-built plaintext kernel cannot boot directly.

**Approach**: do not attack the signature. Instead, make both boot legs of `bootsys` fail at the same time so U-Boot stops and drops into the prompt on its own.

```
NORM leg → read boot partition     ┐
                                    ├─ cut both → boot system norm failed, try boot safe!
SAFE leg → read system/loader      ┘            → gxl_p211_v1#   ✅ console obtained
```

See [docs/01-bad-package-fallback.md](docs/01-bad-package-fallback.md) for the exact procedure.

> ⚠️ A package that only breaks the kernel while keeping env will enter a `Resetting CPU` loop and **will not** fall back to the prompt.
> The only verified combination is “broken boot + no env + no system” at the same time.

### 2.2 The reduced U-Boot has opaque commands

This U-Boot has its output path heavily trimmed: commands such as `help`, `md`, and `printenv <name>` **exist but produce no echo**.
“No output” does not mean “command not present”. Relying on the `help` list alone causes serious false negatives.

**Solution**: the hush `echo` channel still works; use probe expressions to bypass the trimmed output:

```sh
if <cmd>; then echo PB_OK_n; else echo PB_NO_n; fi
```

`scripts/probe/probe_uboot_cmds.ps1` automatically iterates over safe commands and summarizes `OK / NO / UNKNOWN`.
The full command list (usage, dangerous commands, and tricks to bypass output trimming) is in
[docs/02-command-audit.md](docs/02-command-audit.md).

---

## 3. Repository structure

```
b860-gaoan-box/
├── README.md
├── LICENSE
├── docs/
│   ├── 01-bad-package-fallback.md   Bad-package creation + automatic U-Boot fallback (including failed examples)
│   ├── 02-command-audit.md          Probe method + step-by-step procedure + full command list
│   ├── 03-flash-linux-persist.md    Flash Linux to eMMC + boot after power loss
│   ├── 04-kernel-build-network.md   Kernel build + serial/network debugging
│   ├── 05-troubleshooting.md        Common issues
│   └── 06-end-to-end-checklist.md   End-to-end checklist (8 stages)
├── scripts/
│   ├── build/
│   │   ├── aml.py                    AML v2 package parse / verify / assemble
│   │   ├── build_prompt_package.py   Both-legs-broken bad package (prompt fallback, recommended)
│   │   ├── build_bad_boot_package.py Single-leg bad package (kernel only, failed example kept for reference)
│   │   ├── build_ubootshell.py       Good kernel + no env/system prompt package
│   │   └── build_persist_package.py  Persistent boot package (corrected env)
│   ├── probe/
│   │   ├── probe_uboot_cmds.ps1      Batch probe
│   │   └── uboot_cmd.ps1             Send commands one by one at the prompt
│   ├── flash/
│   │   └── check_burnmode.ps1        Detect cold BootROM / U-Boot download mode
│   ├── deploy/
│   │   ├── dev.py                    Device network command channel
│   │   └── push_rootfs.py            Chunked rootfs push
│   ├── device/
│   │   ├── restore_regs.sh           Restore 1080p geometry
│   │   ├── gwctl.sh                  HTTP gateway (schedules restore at boot)
│   │   └── safe_reboot.sh            Watchdog hard reset
│   └── display_model.py              Display geometry model + self-test
└── templates/
    └── v4_spec.reference.json        Reference structure for persistent-package items
```

---

## 4. Script inventory

| Script | Purpose | Key environment variables / arguments |
|---|---|---|
| `build/build_prompt_package.py` | Build a bad package that falls back to the prompt | `B860_V3_IMG`, `B860_V3_KERNEL`, `B860_PROMPT_IMG` |
| `build/build_bad_boot_package.py` | Single-leg bad package (kernel only, failed example; `--restore` can restore the boot partition) | Same as above; outputs `B860_RESCUE_IMG` |
| `build/build_persist_package.py` | Persistent boot package (RGB/1080p env) | `B860_V3_IMG`, `B860_ENV_V3`, `B860_V4_IMG` |
| `build/build_ubootshell.py` | Good kernel + no env/system prompt package | `B860_V3_IMG`, `B860_V3_KERNEL`, `B860_UBOOTSHELL_IMG` |
| `build/aml.py` | Package parse / verify / assemble | `python aml.py info\|verify\|extract\|build` |
| `probe/probe_uboot_cmds.ps1` | Batch-probe available commands | `-Port`, `-ProbeWaitMs`, `-ExtraCmds`, `-CmdFile` |
| `probe/uboot_cmd.ps1` | Run a command at the prompt | `-Cmds printenv`, etc. |
| `flash/check_burnmode.ps1` | Determine flashing mode | `-LogRoot` (flashing tool log directory) |
| `deploy/push_rootfs.py` | Push rootfs to eMMC | `B860_HOST`, `B860_ROOTFS_IMG`, `--seg`, `--verify` |
| `deploy/dev.py` | Device TCP command channel | `B860_HOST`, `B860_SHELL_PORT` |
| `display_model.py` | Geometry model self-test | `--selftest` |

---

## 5. Quick start (in order)

### Step 1: Get the U-Boot prompt

```powershell
# 1) Generate a "both legs broken" bad package from the source package and kernel
$env:B860_V3_IMG     = 'out/v3.img'
$env:B860_V3_KERNEL  = 'out/boot_v3_kernel.bin'
$env:B860_PROMPT_IMG = 'out/prompt.img'
python scripts\build\build_prompt_package.py

# 2) Flash in cold BootROM mode (power off completely → connect USB → power on → flash)
# 3) Power on and watch the serial console
#    Expected: boot system norm failed, try boot safe! → gxl_p211_v1#
```

### Step 2: Discover available commands

Verify serial execution evidence first, then run the batch probe:

```powershell
# 2.1 Confirm commands really execute (expected echo: CHAN_42_OK + PROBE_OK)
pwsh -NoProfile -File scripts\probe\uboot_cmd.ps1 -Port COM14 `
     -Cmds 'if echo CHAN_$((6*7))_OK; then echo PROBE_OK; fi'

# 2.2 Batch-probe safe commands (outputs an OK / NO / UNKNOWN summary)
pwsh -NoProfile -File scripts\probe\probe_uboot_cmds.ps1 -Port COM14

# 2.3 Append custom commands, or batch-read them from a file
pwsh -NoProfile -File scripts\probe\probe_uboot_cmds.ps1 -Port COM14 `
     -ExtraCmds 'help','bdinfo','iminfo'
pwsh -NoProfile -File scripts\probe\probe_uboot_cmds.ps1 -Port COM14 -CmdFile cmds.txt
```

Logs are in `out\probe\probe-*.log`.
For how to recheck `UNKNOWN`, manually retest commands with side effects, and archive results, see
[docs/02 §3 procedure](docs/02-command-audit.md#3-操作步骤逐步).

### Step 3: Flash the persistent Linux package

```bash
# Generate a persistent package with correct env (init_display + RGB + storeargs)
B860_V3_IMG=out/v3.img B860_ENV_V3=out/env_v3.bin B860_V4_IMG=out/persist.img \
  python3 scripts/build/build_persist_package.py
# Flash persist.img in cold BootROM mode
```

### Step 4: Push rootfs

```bash
export B860_HOST=192.0.2.100            # example address; change to match your setup
export B860_ROOTFS_IMG=/path/rootfs.img
python3 scripts/deploy/push_rootfs.py
```

### Step 5: Verify persistence across power loss

Unplug power → power on again → the serial console should show, in order:

```
GXLX2:BL1 → DSH_AUTOBOOT → Linux version → Freeing unused kernel → B860AV2.1-T ~ #
```

No key press is needed. For detailed criteria, see
[docs/03-flash-linux-persist.md](docs/03-flash-linux-persist.md).

> The complete staged checklist (8 stages, pass conditions for each step, and failure fallbacks) is in
> [docs/06-end-to-end-checklist.md](docs/06-end-to-end-checklist.md).

---

## 6. Key parameter quick reference

### 6.1 Boot slots (inside the persistent package's system item)

| Payload | Package offset | Length | Loaded into DDR |
|---|---|---|---|
| Image | `0x38400000` | `0x0119B808` | `0x12000000` |
| DTB | `0x395C0000` | `0xA2A2` | `0x0F000000` |
| initrd | `0x39600000` | `0x1218A6` | `0x14000000` |
| trampoline | `0x39800000` | `0x100` | `0x0E000000` |

`storeargs` chain:

```
store read system 0x12000000 0x38400000 0x0119B808;
store read system 0x0F000000 0x395C0000 0xA2A2;
store read system 0x14000000 0x39600000 0x1218A6;
store read system 0x0E000000 0x39800000 0x100;
go 0x0E000000
```

### 6.2 rootfs

| Item | Value |
|---|---|
| Device node | `/dev/mmcblk2` (whole disk without partition table) |
| Offset | 3072 MiB (3 GiB) |
| Mount | `losetup -o 3221225472` + `mount -t ext4` |
| Push chunks | 256 MiB × 10, two-stage nc |

### 6.3 env

| Item | Value |
|---|---|
| Size | 64 KiB |
| Format | `u32 CRC32` + `key=value\0...` |
| CRC coverage | `blob[4:65536]` |
| Write method | env item inside the flashing package; or `setenv` + `saveenv` at the prompt. **Raw writes to `0x38000000` do not work** |

---

## 7. Risks

1. **Flashing can brick the device**: the flashing tool runs `amlmmc erase 1` (about 108MB–7.22GB);
   rootfs and custom files will be lost. Back up first.
2. **Do not bypass the flashing tool to `dd` the boot partition**: absolute offsets are not verified on real hardware.
3. **The bad package is only for entering the prompt**; do not use it as a daily system.
4. **Dangerous commands can hang or brick the device**: `store erase/scrub/rom_write/mbr`, `efuse write`,
   `bootm <garbage address>`, `go <garbage address>`, `fastboot`, `update` (blocking).
5. **The serial port must be exclusive**, otherwise scripts cannot open it.
6. **Gao'an signatures are not cracked**: this document does not replace BL1/BL2/BL31/BL33 and does not forge signatures.

---

## 8. Open items

| # | Item | Status |
|---|---|---|
| 1 | Device hardware details | Full specification table added from on-device measurements; original annotation “精” retained and explained |
| 2 | Complete build chain for the source package (v3) | This repository only contains incremental scripts for bad and persistent packages |
| 3 | rootfs image generation method | debootstrap arguments and package sources not recorded |
| 4 | Serial port number | Examples use COM14; change according to actual enumeration |
| 5 | Flashing tool version | Several versions appear in records; start with 2.2.4 |
| 6 | SSH verification status | Existing records only verified telnet:23 / nc:2323 / HTTP:8080; SSH not verified (see docs/04) |
| 7 | v3/v4 images and rootfs distribution | No 1GB-scale binaries included; prepare them yourself |
| 8 | Kernel version | Records contain both 6.12.115 and 7.x builds; trust the actual kernel inside the source package (confirm with `uname -r`) |

---

## 9. Releases and assets

**Why are no assets uploaded?** This project only delivers text files: scripts, documentation, and templates.
No Release had been created before, and no firmware images had been uploaded to the repository, so the Releases page shows no assets.
This is not a missing upload; 1GB-scale binaries were never part of the distribution scope.

The Release to be created will attach a **source ZIP of the repository** (README, docs, scripts, templates, LICENSE, and other text files only).
Download it from [Releases (latest)](https://github.com/kaimrdzt/b860-gaoan-hezi/releases/latest).

Firmware images, v3/v4 images, and rootfs are **not distributed with the repository or the Release**, for these reasons:

- **Size**: images are at the 1GB scale, which Git/Releases are not suited to carry;
- **License/copyright**: vendor firmware, kernel binaries, and related components cannot be redistributed here;
- **Redaction**: images may contain device identifiers, keys, or signing material and are not suitable for public upload.

Prepare the source package, kernel, and rootfs from legitimate sources yourself, then generate and push the required images as described in sections 3 and 4.

[Back to top](#top) · [中文](#chinese)

---

## 10. License

Scripts are released under the MIT license (see [LICENSE](LICENSE)).
No vendor firmware, keys, or signing material are included.
