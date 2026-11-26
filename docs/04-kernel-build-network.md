# 04 · 内核编译与网络调试

> 本文分两部分：
> **已验证**：内核编译流程、串口/网络命令通道（telnet:23、nc:2323、HTTP:8080）
> **未验证**：SSH。现有记录中没有 SSH 成功案例，本文只给可执行的集成方法，不声称已通。

---

## 1. 内核编译

### 1.1 环境

| 项 | 值 |
|---|---|
| 构建机 | Linux / WSL，`aarch64-linux-gnu-` 工具链 |
| 内核树 | 6.12.y mainline 分支（`linux-6.12.y-main`） |
| 输出目录 | 独立 `O=` 构建目录 |
| 产物 | `arch/arm64/boot/Image` + 板级 DTB + modules |

> 目标内核版本以实际源码树为准；现有记录另有 7.x 版本产物，**复现时以源包内的
> 内核版本为准**（见待确认项）。

### 1.2 板级 DTS

在 `arch/arm64/boot/dts/amlogic/` 下新增板级 dts，核心是三件事：

```dts
/dts-v1/;
#include "<厂商参考板>.dtsi"

/ {
    compatible = "zte,b860av2t", "amlogic,s905l3b", "amlogic,meson-gxl";
    model = "ZTE ZXV10 B860AV2.1-T (S905L3-B)";
};

/* eMMC */
&sd_emmc_c {
    status = "okay";
    max-frequency = <52000000>;
};

/* 内置百兆 RMII PHY */
&ethmac {
    status = "okay";
};
```

> 上面的 `compatible` / `model` 按原始构建脚本原样保留，不代表本文补写了型号细节。

并把 dtb 加进 Makefile：

```make
dtb-$(CONFIG_ARCH_MESON) += <你的板级>.dtb
```

### 1.3 配置与编译

```bash
export ARCH=arm64
export CROSS_COMPILE=aarch64-linux-gnu-

# 从可启动的旧配置迁移（IKCONFIG 恢复），不要从零 defconfig
cp /path/config-<旧版本> .config
make olddefconfig

make -j"$(nproc)" Image dtbs
make -j"$(nproc)" modules

cp arch/arm64/boot/Image        "$OUT/Image"
cp arch/arm64/boot/dts/amlogic/<板级>.dtb "$OUT/board.dtb"
```

### 1.4 编译后必须验证

| 检查 | 方法 | 期望 |
|---|---|---|
| 架构 | `file Image` | `ARM aarch64` 或裸 Image 标识 |
| 首字魔数 | `xxd -l 4 Image` | `1f 20 03 d5`（NOP） |
| 大小 | `stat -c%s Image` | 记录长度，用于槽位 `store read` |
| DTB 魔数 | `xxd -l 4 board.dtb` | `d0 0d fe ed` |
| 启动参数 | `fdtget board.dtb /chosen bootargs` | 含 `initcall_blacklist` 等 |

> `Image` 不是 ELF，`readelf` 会报错；要看符号请查 `vmlinux`。

### 1.5 常见编译坑

| 现象 | 原因 | 处理 |
|---|---|---|
| `Cannot attach to PHY (-19)` | 缺 `CONFIG_MDIO_BUS_MUX_MESON_GXL=y` | 从可启动内核配置恢复后单独打开 |
| printk 时间戳乱跳 | 新旧配置差异过大 | 用 IKCONFIG 对齐配置 |
| 内核起来但无 shell | DTB `/chosen/bootargs` 缺关键参数 | 参数编进 DTB，不要只改 env |
| 打包后不启动 | 槽位长度与实际文件不符 | 重新按实际长度生成 `storeargs` |

---

## 2. 网络调试通道

### 2.1 已验证的通道

| 通道 | 端口 | 用途 | 状态 |
|---|---|---|---|
| telnetd | 23 | 登录 shell（提示符与串口一致） | ✅ 已验证 |
| nc 命令通道 | 2323 | 脚本化执行命令（`nc -lk -p 2323 -e /bin/sh`） | ✅ 已验证 |
| HTTP 网关 | 8080 | 状态查询 / CGI | ✅ 已验证 |
| 文件推送 | 5559 | `nc` 两段式传文件 | ✅ 已验证 |

前提：

- rootfs 已挂载（`/mnt/r`），init 已完成网络配置
- PC 与盒子同网段
- 示例地址 `192.0.2.100`，按实际替换

### 2.2 命令通道

```python
# dev.py 用法
from dev import Dev
d = Dev(host='192.0.2.100')
print(d.sh('uname -r'))
print(d.alive())
```

```bash
python3 scripts/deploy/dev.py sh "uname -r"
```

### 2.3 SSH（未验证）

现有记录中没有 SSH 成功案例。若要补上，两条路：

**A. Debian rootfs 内安装（最简单）**

```sh
# 设备上（需要 rootfs 可写、软件源可用）
apt-get update
apt-get install -y dropbear-bin        # 或 openssh-server
/etc/init.d/dropbear start             # dropbear
# 或 systemctl enable --now ssh         # openssh
```

需要确认：

- rootfs 的 apt 源可用
- 设备时间正确（否则 SSH 握手可能失败）
- root 登录策略（`PermitRootLogin` / 密码或密钥）

**B. 交叉编译静态 dropbear 放进 initramfs**

适合 rootfs 还没就绪时救急，但要处理：

- 静态链接（`--disable-zlib --disable-syslog` 可减小体积）
- host key 生成与持久化（放 `/mnt/r`，不要放 tmpfs）
- initramfs 体积上限（本机 DTB 窗口为 2 MiB）

> 在实测通过前，请把 SSH 视为**未验证**，网络调试优先用 telnet:23 / nc:2323。

### 2.4 串口调试

| 项 | 值 |
|---|---|
| 参数 | 115200 8N1，DTR/RTS 置位 |
| 发送纪律 | 20 B / 25 ms 分块 + `\r`，整行快发会吃字符 |
| 独占 | 运行脚本前关闭所有串口工具 |
| 日志 | 建议全程落盘，便于回放断言 |

---

## 3. 调试顺序建议

1. **串口**：确认能进 U-Boot 提示符、能跑 `echo` 探针
2. **内核**：`store read` + `go` 能起到 `Freeing unused kernel`
3. **initramfs**：能挂 rootfs、起 telnetd
4. **网络**：telnet:23 / nc:2323 可用
5. **SSH**：在以上都稳定后再集成（当前未验证）
