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

判定规则：

| 串口看到 | 含义 | 下一步 |
|---|---|---|
| `PB_OK_7` | 命令存在且执行成功 | 记录为可用 |
| `PB_NO_7` | 命令存在，但返回非 0（缺参数/语法不对） | 补参数重测 |
| 两个都没有 | 输出被裁，或命令不存在 | 用 §3.4 的方法复核 |

---

## 3. 操作步骤（逐步）

### 3.1 准备

1. **进入提示符**：按 [01](01-bad-package-fallback.md) 刷“双腿全断”坏包，上电看到 `gxl_p211_v1#`。
2. **关闭所有串口工具**：MobaXterm、PuTTY、串口助手、烧录工具的串口监视，全部关闭。
   脚本需要独占端口，否则报 `Access to the port 'COM14' is denied`。
3. **确认串口号**：设备管理器 → 端口 → 记下 CH340 的 COM 号（脚本示例用 `COM14`）。
4. **建日志目录**：

   ```powershell
   New-Item -ItemType Directory -Force out\probe | Out-Null
   ```

### 3.2 验证串口与执行证据

先不要跑批量脚本，先确认“能发进去、能回出来”：

```powershell
pwsh -NoProfile -File scripts\probe\uboot_cmd.ps1 -Port COM14 `
     -Cmds 'if echo CHAN_$((6*7))_OK; then echo PROBE_OK; fi'
```

**预期输出**（日志文件与屏幕都会出现）：

```
CHAN_42_OK
PROBE_OK
```

- 只看到命令原文（例如 `if echo CHAN...`）没有 `CHAN_42_OK` → 串口只回显、命令没执行，
  检查是否真的停在提示符、是否少发回车
- 完全没有输出 → 串口没连对、端口被占用、或设备不在提示符
- 有 `CHAN_42_OK` 但没有 `PROBE_OK` → 命令执行了但条件判断失败，先排查 hush 语法

> 这一步不通过，后面所有探测结果都不可信。

### 3.3 自动探测安全命令

```powershell
pwsh -NoProfile -File scripts\probe\probe_uboot_cmds.ps1 -Port COM14
```

脚本会：

1. 等待串口释放（默认最多 240 秒）
2. 对默认列表逐条发送探针（20 B / 25 ms 慢发）
3. 每条等待独立标记，超时记 `UNKNOWN`
4. 写日志到 `out\probe\probe-<时间戳>.log`
5. 末尾打印“已知存在但会阻塞/改状态”的命令清单

**输出示例**：

```
[OK]   printenv       PB_OK_1
[OK]   echo           PB_OK_2
[NO]   md             PB_NO_5
[?]    ping           no marker | raw: ping
...
=== summary: OK=31 NO=2 UNKNOWN=3 ===
```

**结果解读**：

| 标记 | 处理 |
|---|---|
| `[OK]` | 命令可用，记录到 §4 清单 |
| `[NO]` | 命令存在但裸敲失败，补参数后重测（见 3.4） |
| `[?]` | 输出被裁或真的不存在，用 3.4 复核 |

**预期基线**（2026-11-13 实测）：`printenv`、`store`、`imgread`、`mmcinfo`、
`vout`、`hdmitx`、`osd`、`bmp`、`i2c`、`gpio`、`efuse`、`bootm`、`go` 等应为 OK。

### 3.4 复核 UNKNOWN

对每个 `[?]` 按下面顺序试，直到能确定“存在/不存在”：

**① 补参数再探**

裸命令可能因为缺参数返回非 0。例如：

```sh
if store dtb read 0x0F000000 0x1000; then echo PB_STORE_DTB_OK; else echo PB_STORE_DTB_NO; fi
```

**② 用行为验证，而不是看回显**

```sh
# 内存里找一个已知值，用 itest 解引用判断
if itest.l *0x0F000000 == 0xd00dfeed; then echo DTB_MAGIC_OK; else echo DTB_BAD; fi

# 写一个字节再读回（选安全地址，测完恢复）
mw.b 0x0E000000 0x5a 1
if itest.b *0x0E000000 == 0x5a; then echo MW_OK; else echo MW_BAD; fi
```

**③ 用 `help <cmd>` 的 usage**

部分命令的 `help <cmd>` 有 usage（如 `store`、`imgread`、`hdmitx`、`osd`、`bmp`、`i2c`、`gpio`、`efuse`）。
看到 usage 就说明命令存在，即使裸敲无回显。

**④ 仍无法判定**

在清单里记 `未判定`，不要猜。写清试过哪些方式。

### 3.5 手动补测有副作用/会阻塞的命令

这类命令**不要放进自动批量列表**，逐条手动执行，并先确认后果。

**setenv（改环境变量）**

```sh
if setenv PB_TMP 1; then echo PB_SETENV_OK; fi
setenv PB_TMP            # 删除临时变量
printenv                 # 裸敲确认已恢复
```

**saveenv（写 env 分区）**

```sh
# 确认当前 env 正确后再执行；写入后跨重启验证
saveenv
```

**mw（写内存）**

```sh
mw.b <安全地址> 0x5a 1   # 只写 1 字节
if itest.b *<安全地址> == 0x5a; then echo MW_OK; fi
```

**run / autoscr（执行变量脚本）**

```sh
setenv PB_SCRIPT 'echo RUN_OK_456'
if run PB_SCRIPT; then echo RUN_EXISTS; fi
setenv PB_SCRIPT
```

**以下命令只确认“存在”，不要实际执行完**：

| 命令 | 验证方式 | 风险 |
|---|---|---|
| `reset` / `reboot` | 看 `help reboot` 的 usage | 会重启设备 |
| `fastboot` | 看 usage | 阻塞，脱困需断电 |
| `update` / `sdc_burn` | 看 usage | 阻塞 |
| `loadb` / `loady` | 看 `help` 是否打印 usage | 阻塞等待串口数据 |
| `tftpboot` | 看 usage | 需要 serverip，会发网络请求 |
| `bootsys` | 看 bootcmd 引用 | 会尝试启动 |
| `wipeisb` | 不测 | 语义未知 |

### 3.6 归档结果

1. 打开 `out\probe\probe-<时间戳>.log`，把 `[OK]` / `[NO]` / `[?]` 三组分别汇总。
2. 对照 §4 的清单，标记差异：
   - 本机有、清单没有 → 新增到清单
   - 清单有、本机 `[NO]` → 补参数或标注差异
3. 把日志路径写进提交记录，便于回溯。

建议的最终记录格式：

```
探测时间：2026-11-13
固件：<横幅/版本>
OK=31  NO=2  UNKNOWN=3
日志：out/probe/probe-20261113-170521.log
未判定：mtest, source, loadb
```

### 3.7 扩展新命令

三种方式：

**追加几条**

```powershell
pwsh -NoProfile -File scripts\probe\probe_uboot_cmds.ps1 -Port COM14 `
     -ExtraCmds 'help','bdinfo','iminfo','mtest'
```

**从文件读（推荐，命令多时）**

新建 `cmds.txt`：

```
# 每行一个命令，# 开头为注释
help
bdinfo
iminfo
mtest
ifconfig
dhcp
```

```powershell
pwsh -NoProfile -File scripts\probe\probe_uboot_cmds.ps1 -Port COM14 -CmdFile cmds.txt
```

**调超时**

某些命令响应慢（如 `mmcinfo`、`usb start`），把 `-ProbeWaitMs` 调到 2500：

```powershell
pwsh -NoProfile -File scripts\probe\probe_uboot_cmds.ps1 -Port COM14 -ProbeWaitMs 2500
```

---

## 4. 完整命令清单

### 4.1 环境变量

| 命令 | 用法 | 状态 |
|---|---|---|
| `printenv` | 裸敲 = 全部 env | ✅ 实测打印 73 个变量 |
| `setenv` | `setenv [-f] name value...`；`setenv name` 删除 | ✅ 可用 |
| `saveenv` | 保存到 store env 分区 | ✅ 探针 OK |
| `run` | `run var [...]` | ✅ 实证 |
| `defenv_reserv` | 恢复默认 env 并保留指定项 | ⚠️ env 脚本引用，未单独探测 |

### 4.2 hush / 流程

| 命令 | 用法 | 状态 |
|---|---|---|
| `echo` | `echo <str>` | ✅ 探针通道本体 |
| `test` | `test <args>` | ✅ |
| `itest` | `itest[.b/.w/.l/.s] value1 <op> value2` | ✅ 有 usage；`=` 语法不对，env 脚本用 `==` |
| `if/then/else/fi` | hush 语法，提示符可直接用 | ✅ |
| `sleep` | `sleep N` | ✅ |
| `autoscr` | `autoscr [addr]` 跑内存脚本 | ✅ usage |
| `source` | 类似 autoscr | ⚠️ 静默，未判定 |

### 4.3 内存（读被裁，写可用）

| 命令 | 用法 | 状态 |
|---|---|---|
| `md` / `md.b` / `md.w` | `md[.b|.w] addr [count]` | ⚠️ 存在，**显示被裁** |
| `mw` / `mw.b` | `mw[.b] addr value [count]` | ✅ 可写内存 |
| `cp.b` | `cp.b src dst count` | ✅ |
| `cmp.b` | `cmp.b a b count` | ✅ |
| `crc32` | `crc32 addr count` | ✅（结果回显被裁） |
| `base` | 显示/设置默认地址基数 | ✅ |
| `mtest` | 内存测试 | ⚠️ help 静默，未验证 |

### 4.4 存储 / 镜像

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

### 4.5 显示 / HDMI

| 命令 | 用法 | 状态 |
|---|---|---|
| `vout` | `vout output [list \| format]` | ✅；list 输出被裁 |
| `hdmitx` | `hdmitx hpd`；`hdmitx output [list \| FORMAT \| bist MODE]`；`hdmitx blank [0|1]`；`hdmitx off`；`hdmitx info` | ✅；FORMAT 支持 `8bits/10bits, y444/y422/y420/rgb`；`bist 1/2/3` = 内置彩条/线条/点阵 |
| `osd` | `osd open/enable/close/clear/debug/test/display <addr> [x y]` | ✅ |
| `bmp` | `bmp info/display <addr> [x y]`；`bmp scale` | ✅ |
| `jpeg` | `jpeg display <outputmode>` | ✅ |
| `cvbs` | `cvbs init/debug/output [mode \| bist ...]/vdac 0-3` | ✅ |

### 4.6 硬件工具

| 命令 | 用法 | 状态 |
|---|---|---|
| `i2c` | `md/mw/nm/probe/read/write/loop/crc32/reset/speed` | ✅ 全套 |
| `gpio` | `gpio <input|set|clear|toggle> <pin>`；`gpio status [-a]` | ✅ |
| `efuse` | `efuse read/write offset size [data]` | ✅；**写 efuse 不可逆** |
| `keyman` | `init/read/write/query/exit` | ✅ usage；`init` 需要有效 DTB |
| `irkey` | `irkey <6 个键值> time_value` | ✅ |
| `getCom` | — | ✅ 探针 OK |

### 4.7 启动

| 命令 | 用法 | 状态 |
|---|---|---|
| `bootm` | `bootm [addr [arg [dtb]]]`，子命令 `start/loados/ramdisk/fdt/cmdline/bdt/prep/go` | ✅ |
| `go` | `go addr [arg...]` | ✅ |
| `bootsys` | 原厂启动逻辑 | ✅ bootcmd 在用 |
| `reset` | 立即重启 | ✅ usage |
| `reboot` | `reboot [cold_boot/normal/factory_reset/recovery/update/usb_burning/suspend_off/hibernate/crash_dump]` | ✅ 可指定模式 |
| `get_rebootmode` | 查询重启原因 | ✅（回显被裁） |
| `wipeisb` | 语义未知 | ⚠️ 慎用 |

### 4.8 网络

| 命令 | 用法 | 状态 |
|---|---|---|
| `tftpboot` | `tftpboot [addr] [[hostIP:]file]` | ✅ usage 打印，网络栈可能可用 |
| `ping` | `ping <ip>` | ⚠️ 静默，存在性未判定 |
| `loadb` / `loady` | 串口下载 | ⚠️ help 静默；若存在则是串口传文件通道；运行会阻塞 |

---

## 5. 明确不存在或不适用

| 命令 | 结果 |
|---|---|
| `video` | ❌ 无 usage，大概率不存在 |
| `booti` / `bootz` / `boot` / `bootd` | ⚠️ help 静默，无法判定 |
| `iminfo` / `imxtract` / `unzip` | ⚠️ help 静默 |
| `source` / `esi` | ⚠️ 静默 |

> 对“静默”类命令，用 `if <cmd>; then echo ...; fi` 探针再确认一次。

---

## 6. 绕过“输出被裁”的三个技巧

### 6.1 `itest` 解引用读内存

`help itest` 的 `[*]value` 星号前缀表示解引用：

```sh
# DTB 魔数
if itest.l *0x0F000000 == 0xd00dfeed; then echo DTB_MAGIC_OK; else echo DTB_BAD; fi

# ARM64 Image 首字（NOP 0xd503201f，字节序 1f 20 03 d5）
if itest.l *0x12000000 == 0xd503201f; then echo IMG_MAGIC_OK; else echo IMG_BAD; fi
```

### 6.2 `crc32` 当布尔校验

```sh
if crc32 0x12000000 0x119b808 <expected>; then echo CRC_OK; fi
```

> 该 build 是否支持第三个参数需实测；不支持时只用两参并读回显（回显可能被裁）。

### 6.3 长脚本分段 `setenv`

```sh
setenv storeargs "${storeargs} 后续片段"
```

长命令按 20 B / 25 ms 慢发，多条 `setenv` 拼接，避免整行被截断。

---

## 7. 危险命令（不要在自动探测里执行）

| 命令 | 风险 |
|---|---|
| `store erase ...` / `store scrub` / `store rom_write` / `store mbr` | 破坏分区/引导 |
| `efuse write` | 不可逆，可能永久变砖 |
| `bootm <垃圾地址>` / `go <垃圾地址>` | 跳转到无效地址 → 复位 |
| `reset` / `reboot` | 立即重启，丢失当前内存态 |
| `fastboot` / `update` / `sdc_burn` / `loadb` / `loady` | 阻塞等待，脱困需断电 |
| `setenv` / `saveenv` | 改变持久化配置，误改会导致无法启动 |
