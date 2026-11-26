# 01 · 坏包制作与自动回落 U-Boot

> 目的：原厂 U-Boot 正常启动时无法打断（按键/串口都进不去），
> 通过刷入一个“坏的刷机包”，让 `bootsys` 两条启动腿同时失败，
> 盒子会主动停在 `gxl_p211_v1#` 提示符，从而获得控制台。

---

## 1. U-Boot 的启动结构

该 U-Boot 的 `bootcmd` 走 `bootsys`，它内部有两条腿：

| 腿 | 读取位置 | 触发条件 |
|---|---|---|
| NORM | `boot` 分区（Android bootimg，AES + RSA-2048） | 正常启动 |
| SAFE | `system` / bootloader 备份 | NORM 失败后 |

失败时的典型日志：

```
boot system norm failed, try boot safe!
gxl_p211_v1#
```

**关键结论**（2026-11-13 实机验证）：

- 只让 NORM 失败（只坏内核）→ 会尝试 SAFE；若 SAFE 能启动，仍拿不到控制台
- 若 SAFE 也失败 → 停提示符
- 若 **env 有效** 且 `storeargs` 链存在 → 即使内核坏，也可能直接 `Resetting CPU` 死循环，**不会**停提示符

---

## 2. 两种坏包的实测结果

| 方案 | 内容 | 结果 |
|---|---|---|
| A. 单腿坏包 | 坏 boot（前 64 KiB 清零）+ 保留 env + 无 system | ❌ `DSH_AUTOBOOT` 后 `Resetting CPU ...` 硬复位死循环 |
| B. 双腿全断包 | 坏 boot + **无 env** + **无 system** | ✅ `boot system norm failed, try boot safe!` → `gxl_p211_v1#` |

> 方案 A 的脚本保留为 `scripts/build/build_bad_boot_package.py`，仅作反例与对照，**不要**用它去追求提示符。

方案 B 的实机日志（2026-11-13 16:55）：

```
osd_size 1080p → bootmode:NORM → boot system norm failed, try boot safe! → gxl_p211_v1#
```

---

## 3. 制作“双腿全断”坏包

### 3.1 原理

从源包（已验证可启动的整包）出发，只改三件事：

1. **boot item 改成坏内核**：把原版 boot 分区内容的前 64 KiB 清零，长度保持不变
2. **删除 env item**：烧录时 `amlmmc erase` 会把 env 分区擦空，且包内不回写 → 回默认环境
3. **删除 system item**：SAFE 腿没有可读的 system → 也失败

保留项（缺一不可）：

| item | 作用 |
|---|---|
| `DDR` / `DDR_ENC` | 烧录工具初始化内存 |
| `UBOOT` / `UBOOT_ENC` | 引导本体，必须原样，否则没有提示符 |
| `meson1`（dtb） | 板级参数 |
| `platform`（conf） | 平台配置 |

### 3.2 执行

```bash
export B860_V3_IMG=/path/to/v3.img            # 已验证可启动的源包
export B860_V3_KERNEL=/path/to/boot_v3_kernel.bin   # 源包 boot 分区的原始内容
export B860_PROMPT_IMG=/path/to/prompt.img
export B860_PARTS_DIR=/path/to/parts_prompt

python3 scripts/build/build_prompt_package.py
```

脚本会：

- 从源包抽取保留项
- 生成 `boot_bad.bin`（前 64 KiB 清零）
- 组包并重算 `boot` 的 VERIFY（`sha1sum <40hex>` 文本，48 字节）
- 重算包头 CRC（`crc32(file[4:]) ^ 0xFFFFFFFF`）
- 用 `aml.py` 做结构校验，并断言 **无 env、无 system**

产物约 11–12 MiB（不含 1 GiB system）。

### 3.3 包结构参考

```json
{
  "items": [
    {"name":"DDR","fmt":"USB"},
    {"name":"DDR_ENC","fmt":"USB"},
    {"name":"UBOOT","fmt":"USB"},
    {"name":"UBOOT_ENC","fmt":"USB"},
    {"name":"boot","fmt":"PARTITION","size":9763328},
    {"name":"boot","fmt":"VERIFY","size":48},
    {"name":"meson1","fmt":"dtb"},
    {"name":"platform","fmt":"conf"}
  ]
}
```

---

## 4. 烧录与验证

### 4.1 进入冷 BootROM 模式

1. **彻底断电**（拔电源，不是软复位）
2. 接 USB 双公头线到 OTG 口
3. 给盒子上电
4. 烧录工具载入 `prompt.img`

> 如果设备已经停在别的状态、烧录工具复用了设备里的 U-Boot（“U-Boot 从模式”），
> 会触发 `store ddr_parameter erase` 失败。必须彻底断电重来。

### 4.2 上电观察

串口 115200 8N1，预期：

```
boot system norm failed, try boot safe!
gxl_p211_v1#
```

看到提示符后即可执行命令。常用：

```sh
printenv                 # 裸敲，全量输出（printenv name 无回显）
help                     # 部分 build 无输出，属正常
```

### 4.3 确认拿到了控制台

```sh
if echo CHAN_$((6*7))_OK; then echo PROBE_OK; fi
```

预期回显 `CHAN_42_OK` 与 `PROBE_OK`。这是后续所有探针与操作的执行证据。

---

## 5. 进入提示符之后

1. 用 [02-command-audit.md](02-command-audit.md) 的探针脚本盘点可用命令
2. 在提示符上验证关键命令（例如 HDMI 输出、内存读写）
3. 需要恢复系统时，重新烧入持久化包（[03](03-flash-linux-persist.md)）

> 提示符状态是**临时**的：断电重启后仍会回到提示符（因为 env 已空、两条腿仍断）。
> 这是预期行为，不是故障。

---

## 6. 常见误区

| 误区 | 事实 |
|---|---|
| “只要内核坏了就会停提示符” | 错。env 有效时会 `Resetting CPU` 死循环 |
| “去掉 system 就能保 rootfs” | 错。烧录工具的 `amlmmc erase` 会擦 108MB–7.22GB，rootfs 一定丢 |
| “用按键/串口狂按 Enter 可以打断” | 该 U-Boot 没有可用打断窗口，实测无效 |
| “坏包会破坏 bootloader” | 不会。DDR/UBOOT 等 USB 项原样保留 |
