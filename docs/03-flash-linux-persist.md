# 03 · 刷入 Linux 并实现掉电自启

> 目标：把自编 Linux 内核与 rootfs 放进 eMMC，上电后不按任何键自动启动，
> 断电重启后仍能引导，并且 rootfs 数据保留。

---

## 1. 为什么不能走官方启动链

| 约束 | 后果 |
|---|---|
| Secure Boot 开启 | `bootsys → imgread kernel boot` 会做 AES 解密 + RSA-2048 验签，明文自编内核必失败 |
| `bootm` 可用但受限于验签 | 直接 `bootm` 自编镜像不可行 |
| 新内核 `text_offset=0` | `booti` 会 `Resetting CPU` |

**可行路径**：用 `store read` 裸分区读（不解密、不验签）把载荷读进固定 DDR 地址，
再用 trampoline 把 CPU0 从 EL2 降到 EL1，`go` 跳转内核。

```
preboot = run init_display; run storeargs;
storeargs = echo DSH_AUTOBOOT; setenv bootargs <BA>; <CHAIN>
```

`preboot` 在每次启动时无条件执行，所以不需要按键，也不需要打断。

---

## 2. eMMC 布局

| 区域 | 内容 |
|---|---|
| boot 分区 | 持久化包中可放 logo（原厂启动链不使用该分区） |
| system item（包内 1 GiB） | 内核 / DTB / initrd / trampoline 四个槽位 |
| **rootfs** | eMMC **3072 MiB** 偏移，1 个 ext4，initramfs 用 `losetup` 挂到 `/mnt/r` |

> 该设备在 Linux 侧只看到 `mmcblk2` 整盘，没有分区表，所以 rootfs 用固定偏移而不是分区。

---

## 3. 持久化启动包

### 3.1 与坏包的区别

| 项 | 坏包（01） | 持久化包 |
|---|---|---|
| boot item | 坏内核 | logo 或原始内容 |
| env item | **无** | **有，且已修正** |
| system item | **无** | **有（内核/DTB/initrd）** |
| 结果 | 停提示符 | 自动启动 Linux |

### 3.2 env 的关键变量

| 变量 | 作用 |
|---|---|
| `init_display` | 建 HDMI 管线 + 显示 logo |
| `storeargs` | 整条 `store read` + `go` 启动链 |
| `outputmode` | `1080p60hz` |
| `display_width` / `display_height` | `1920` / `1080` |

`init_display` 示例：

```
echo HDMIINIT_MARKER;hdmitx hpd;vout output 1080p60hz;
hdmitx output 1080p60hz,8bits,rgb;
store read boot 0x12000000 0 0x620000;osd open;osd clear;bmp display 0x12000000
```

> `hdmitx output ... ,8bits,rgb` 是颜色修复的关键：缺少它时 HDMI 会走 YCbCr，出现偏紫/偏粉。

### 3.3 槽位参数

| 载荷 | 包内偏移 | 长度 | DDR |
|---|---|---|---|
| Image | `0x38400000` | `0x0119B808` | `0x12000000` |
| DTB | `0x395C0000` | `0xA2A2` | `0x0F000000` |
| initrd | `0x39600000` | `0x1218A6` | `0x14000000` |
| trampoline | `0x39800000` | `0x100` | `0x0E000000` |

**四个长度必须与实际文件一致**，否则会出现：

- `Bad Linux ARM64 Image magic`
- `Wrong Ramdisk Image Format`
- `Resetting CPU`
- DTB 被截断导致外设不工作

### 3.4 生成

```bash
export B860_V3_IMG=/path/to/v3.img
export B860_ENV_V3=/path/to/env_item_v3.bin
export B860_V4_IMG=/path/to/persist.img

python3 scripts/build/build_persist_package.py
```

脚本只替换 `env` item，其余 item 与源包逐字节一致，并重算头 CRC。

---

## 4. 烧录与首次启动

1. 彻底断电 → 接 USB → 上电 → 冷 BootROM 模式
2. 烧录 `persist.img`
3. 串口观察：

| 阶段 | 预期 |
|---|---|
| 1–2 秒 | HDMI 显示 logo |
| 串口 | `HDMIINIT_MARKER` |
| 串口 | `DSH_AUTOBOOT` |
| 串口 | `Linux version ...` |
| 串口 | `Freeing unused kernel memory` |
| 串口 | `B860AV2.1-T ~ #` |

> 如果停在 `gxl_p211_v1#` 且无 `DSH_AUTOBOOT`，说明 env 没生效，
> 检查包内是否真的带了 env item、CRC 是否正确。

---

## 5. 推送 rootfs

烧录工具会执行 `amlmmc erase 1`（约 108MB–7.22GB），**rootfs 一定会被擦除**，
所以每次烧录后都要重新推送。

```bash
export B860_HOST=192.0.2.100          # 示例地址
export B860_ROOTFS_IMG=/path/rootfs-deb13-2560m.img

python3 scripts/deploy/push_rootfs.py          # 全量 10 片
python3 scripts/deploy/push_rootfs.py --seg 3  # 单片重试
python3 scripts/deploy/push_rootfs.py --seg 3 --verify
```

每片必须满足：

- PC 发送字节数 = 切片大小
- 设备 `wc -c` 返回值 = 切片大小（脚本内强制校验）
- `dd ... seek=N conv=notrunc` 返回 `DD_RC=0`

> **不要**用 `nc | dd` 直写：在该 busybox 上实测只有 B/s 级；
> 两段式（`nc > /tmp/chunk` 再 `dd`）才稳定。

### 5.1 挂载验证

```sh
losetup -o 3221225472 /dev/loop0 /dev/mmcblk2
mount -t ext4 /dev/loop0 /mnt/r
mount -o remount,rw /mnt/r
mount | grep /mnt/r     # 出现 /dev/loop0 on /mnt/r type ext4 (rw) = 成功
```

ext4 超级块 + 日志 + 元数据都能读出来，是 2.5 GiB 数据完整性的最强证据。

---

## 6. 掉电持久化验证

1. 正常运行状态下**直接拔电源**
2. 重新上电，全程不碰键盘、不接串口输入
3. 串口断言：

| 层 | 断言 |
|---|---|
| L0 | `GXLX2:BL1` |
| L1 | `DSH_AUTOBOOT` |
| L2 | `Linux version` |
| L3 | `Freeing unused kernel` |
| L4 | `B860AV2.1-T ~ #` |

> 软复位也会打印 `BL1`。物理断电与软复位的区别：
> 软复位日志含 `resetting ...`、PSCI Affinity Map、`bl31 reboot reason: 0x1`；
> 物理断电没有这些行。脚本无法证明“物理断电”，只能靠操作纪律。

4. 数据保留验证：

```sh
ls -l /mnt/r/b860/
mount | grep /mnt/r
```

---

## 7. 数据保留边界

| 操作 | rootfs 是否保留 |
|---|---|
| 断电/重启/掉电 | ✅ 保留 |
| 用 `ubiupdatevol` 类原位更新（本机不适用） | — |
| 烧录任意整包（含坏包、持久化包） | ❌ 被 `amlmmc erase` 擦除 |
| 在系统内升级内核（`dd` 写 system item 区） | ✅ 保留，但需精确偏移，风险高 |

因此：**每次烧录前备份 `/mnt/r` 的自定义文件**。
