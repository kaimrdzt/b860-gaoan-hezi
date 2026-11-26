# 02 · 命令探索方法与完整清单

> 探测对象：`gxl_p211_v1#` 提示符（由 [01](01-bad-package-fallback.md) 的坏包进入）
> 探测方法：`if <cmd>; then echo PB_OK_n; else echo PB_NO_n; fi`
> 原始记录：2026-11-13，四批共 47 条探针

---

## 1. 为什么不能直接用 `help`

本版 U-Boot 的**输出路径被大面积裁剪**：

- `help`（裸敲）无输出
- `md` / `md.b` / `md.w` 存在，但读出的内容不显示
- `printenv <name>` 存在，但单变量查询无回显（只能裸 `printenv` 全量）
- `hdmitx info`、`vout output list`、`hdmitx output list` 均无输出

因此 **“无输出” ≠ “命令不存在”**。必须用带执行证据的探针。

---

## 2. 探针原理

该 U-Boot 的 hush 解释器支持 `if / then / else / fi`，且 `echo` 通道可用。
把命令包进条件语句，让 U-Boot 自己回一个唯一标记：

```sh
if <cmd>; then echo PB_OK_7; else echo PB_NO_7; fi
```

- 收到 `PB_OK_7` → 命令存在且执行成功
- 收到 `PB_NO_7` → 命令存在但返回非 0（语法/参数问题，不等于命令缺失）
- 两个都没收到 → 输出被裁或命令不存在，记为 `UNKNOWN`

### 2.1 自动探测

```powershell
pwsh -NoProfile -File scripts\probe\probe_uboot_cmds.ps1 -Port COM14
```

脚本特性：

- 只探测**无副作用、不阻塞**的安全命令
- 串口慢发：20 B / 25 ms，避免长行被吃字符
- 每条命令等待独立标记，超时记 `UNKNOWN`
- 日志写到 `out\probe\probe-<时间戳>.log`
- 末尾列出“已知存在但会阻塞/改状态”的命令，不自动执行

### 2.2 手动单条

```powershell
pwsh -NoProfile -File scripts\probe\uboot_cmd.ps1 -Port COM14 -Cmds printenv,'if echo T_$((6*7)); then echo E_OK; fi'
```

---

## 3. 完整命令清单

### 3.1 环境变量

| 命令 | 用法 | 状态 |
|---|---|---|
| `printenv` | 裸敲 = 全部 env | ✅ 实测打印 73 个变量 |
| `setenv` | `setenv [-f] name value...`；`setenv name` 删除 | ✅ 可用 |
| `saveenv` | 保存到 store env 分区 | ✅ 探针 OK |
| `run` | `run var [...]` | ✅ 实证 |
| `defenv_reserv` | 恢复默认 env 并保留指定项 | ⚠️ env 脚本引用，未单独探测 |

### 3.2 hush / 流程

| 命令 | 用法 | 状态 |
|---|---|---|
| `echo` | `echo <str>` | ✅ 探针通道本体 |
| `test` | `test <args>` | ✅ |
| `itest` | `itest[.b/.w/.l/.s] value1 <op> value2` | ✅ 有 usage；`=` 语法不对，env 脚本用 `==` |
| `if/then/else/fi` | hush 语法，提示符可直接用 | ✅ |
| `sleep` | `sleep N` | ✅ |
| `autoscr` | `autoscr [addr]` 跑内存脚本 | ✅ usage |
| `source` | 类似 autoscr | ⚠️ 静默，未判定 |

### 3.3 内存（读被裁，写可用）

| 命令 | 用法 | 状态 |
|---|---|---|
| `md` / `md.b` / `md.w` | `md[.b|.w] addr [count]` | ⚠️ 存在，**显示被裁** |
| `mw` / `mw.b` | `mw[.b] addr value [count]` | ✅ 可写内存 |
| `cp.b` | `cp.b src dst count` | ✅ |
| `cmp.b` | `cmp.b a b count` | ✅ |
| `crc32` | `crc32 addr count` | ✅（结果回显被裁） |
| `base` | 显示/设置默认地址基数 | ✅ |
| `mtest` | 内存测试 | ⚠️ help 静默，未验证 |

### 3.4 存储 / 镜像

| 命令 | 用法 | 状态 |
|---|---|---|
| `store` | 子命令：`read/write/rom_write/erase boot|data/erase partition <name>/erase dtb/erase key/scrub/dtb iread|read|write/key read|write/mbr/disprotect key/rom_protect on|off` | ✅ usage 完整 |
| `store read env <addr> 0 0x40` | 读 env 分区 | ✅ |
| `store key read <addr>` | 读 key 分区 | ✅ |
| `store dtb read` | 无 size 参数时失败 | ⚠️ 需补 size |
| `imgread` | `imgread kernel/dtb/res/picture <part> <addr> [off]` | ✅；`picture` 可读 logo 分区 |
| `mmcinfo` | eMMC 信息 | ✅ 打印 |
| `usb start 0` | USB 初始化 | ✅ 打印 |
| `fastboot` | 进入 USB fastboot | ⚠️ 存在但**阻塞** |
| `update` | USB 烧录等待 | ⚠️ 阻塞 |
| `sdc_burn` | SD 烧录 | ⚠️ env 引用 |
| `fatload` | `fatload <interface> <addr> <file>` | ⚠️ env 引用 |

### 3.5 显示 / HDMI

| 命令 | 用法 | 状态 |
|---|---|---|
| `vout` | `vout output [list \| format]` | ✅；list 输出被裁 |
| `hdmitx` | `hdmitx hpd`；`hdmitx output [list \| FORMAT \| bist MODE]`；`hdmitx blank [0|1]`；`hdmitx off`；`hdmitx info` | ✅；FORMAT 支持 `8bits/10bits, y444/y422/y420/rgb`；`bist 1/2/3` = 内置彩条/线条/点阵 |
| `osd` | `osd open/enable/close/clear/debug/test/display <addr> [x y]` | ✅ |
| `bmp` | `bmp info/display <addr> [x y]`；`bmp scale` | ✅ |
| `jpeg` | `jpeg display <outputmode>` | ✅ |
| `cvbs` | `cvbs init/debug/output [mode \| bist ...]/vdac 0-3` | ✅ |

### 3.6 硬件工具

| 命令 | 用法 | 状态 |
|---|---|---|
| `i2c` | `md/mw/nm/probe/read/write/loop/crc32/reset/speed` | ✅ 全套 |
| `gpio` | `gpio <input|set|clear|toggle> <pin>`；`gpio status [-a]` | ✅ |
| `efuse` | `efuse read/write offset size [data]` | ✅；**写 efuse 不可逆** |
| `keyman` | `init/read/write/query/exit` | ✅ usage；`init` 需要有效 DTB |
| `irkey` | `irkey <6 个键值> time_value` | ✅ |
| `getCom` | — | ✅ 探针 OK |

### 3.7 启动

| 命令 | 用法 | 状态 |
|---|---|---|
| `bootm` | `bootm [addr [arg [dtb]]]`，子命令 `start/loados/ramdisk/fdt/cmdline/bdt/prep/go` | ✅ |
| `go` | `go addr [arg...]` | ✅ |
| `bootsys` | 原厂启动逻辑 | ✅ bootcmd 在用 |
| `reset` | 立即重启 | ✅ usage |
| `reboot` | `reboot [cold_boot/normal/factory_reset/recovery/update/usb_burning/suspend_off/hibernate/crash_dump]` | ✅ 可指定模式 |
| `get_rebootmode` | 查询重启原因 | ✅（回显被裁） |
| `wipeisb` | 语义未知 | ⚠️ 慎用 |

### 3.8 网络

| 命令 | 用法 | 状态 |
|---|---|---|
| `tftpboot` | `tftpboot [addr] [[hostIP:]file]` | ✅ usage 打印，网络栈可能可用 |
| `ping` | `ping <ip>` | ⚠️ 静默，存在性未判定 |
| `loadb` / `loady` | 串口下载 | ⚠️ help 静默；若存在则是串口传文件通道；运行会阻塞 |

---

## 4. 明确不存在或不适用

| 命令 | 结果 |
|---|---|
| `video` | ❌ 无 usage，大概率不存在 |
| `booti` / `bootz` / `boot` / `bootd` | ⚠️ help 静默，无法判定 |
| `iminfo` / `imxtract` / `unzip` | ⚠️ help 静默 |
| `source` / `esi` | ⚠️ 静默 |

> 对“静默”类命令，用 `if <cmd>; then echo ...; fi` 探针再确认一次。

---

## 5. 绕过“输出被裁”的三个技巧

### 5.1 `itest` 解引用读内存

`help itest` 的 `[*]value` 星号前缀表示解引用：

```sh
# DTB 魔数
if itest.l *0x0F000000 == 0xd00dfeed; then echo DTB_MAGIC_OK; else echo DTB_BAD; fi

# ARM64 Image 首字（NOP 0xd503201f，字节序 1f 20 03 d5）
if itest.l *0x12000000 == 0xd503201f; then echo IMG_MAGIC_OK; else echo IMG_BAD; fi
```

### 5.2 `crc32` 当布尔校验

```sh
if crc32 0x12000000 0x119b808 <expected>; then echo CRC_OK; fi
```

> 该 build 是否支持第三个参数需实测；不支持时只用两参并读回显（回显可能被裁）。

### 5.3 长脚本分段 `setenv`

```sh
setenv storeargs "${storeargs} 后续片段"
```

长命令按 20 B / 25 ms 慢发，多条 `setenv` 拼接，避免整行被截断。

---

## 6. 危险命令（不要在探测脚本里自动执行）

| 命令 | 风险 |
|---|---|
| `store erase ...` / `store scrub` / `store rom_write` / `store mbr` | 破坏分区/引导 |
| `efuse write` | 不可逆，可能永久变砖 |
| `bootm <垃圾地址>` / `go <垃圾地址>` | 跳转到无效地址 → 复位 |
| `reset` / `reboot` | 立即重启，丢失当前内存态 |
| `fastboot` / `update` / `sdc_burn` / `loadb` / `loady` | 阻塞等待，脱困需断电 |
| `setenv` / `saveenv` | 改变持久化配置，误改会导致无法启动 |
