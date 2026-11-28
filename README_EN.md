<p align="center">Language / 语言: <a href="README.md">中文</a> | Current: English (click 中文 to switch)</p>


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
├── README.md                          Chinese README
├── README_EN.md                       English README (this file)
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
