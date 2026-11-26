#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_prompt_package.py — 制作“双腿全断”坏包，让盒子自动回落 U-Boot 提示符

背景
----
该盒子的原厂 U-Boot 在正常启动时没有可用的打断窗口（按键/串口输入都进不去），
但 `bootsys` 有两条启动腿：

    NORM 腿 → 读 boot 分区
    SAFE 腿 → 读 system / bootloader

只要两条腿同时失败，U-Boot 就会停下来打印 `gxl_p211_v1#` 提示符，
从而获得可交互的控制台。

本包同时切断两条腿：
    - boot item = 坏内核（前 64 KiB 清零）  → NORM 必失败
    - 不含 env item                          → 烧录擦除 env，回到默认环境
    - 不含 system item                       → SAFE 腿也失败

2026-11-13 实机验证：烧入后上电，日志为
    boot system norm failed, try boot safe! → gxl_p211_v1#
（注意：只坏内核但保留 env 的包会进入 `Resetting CPU` 死循环，见 docs/01）

用法
----
    python build_prompt_package.py

环境变量
--------
    B860_V3_IMG      源包（提供 DDR/DDR_ENC/UBOOT/UBOOT_ENC/meson1/platform）
    B860_V3_KERNEL   原版 boot 分区内容（长度须与源包 boot item 一致）
    B860_PROMPT_IMG  输出镜像路径
    B860_PARTS_DIR   中间产物目录
"""
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from aml import parse, verify, cmd_build  # noqa: E402

SRC = os.environ.get('B860_V3_IMG', 'out/B860AV21T_v3_arm64_20261111_GA.img')
KERNEL = os.environ.get('B860_V3_KERNEL', 'out/boot_v3_kernel.bin')
DST = os.environ.get('B860_PROMPT_IMG', 'out/B860AV21T_PROMPT_arm64.img')
PARTS = os.environ.get('B860_PARTS_DIR', 'out/parts_prompt')
ZAP_LEN = 65536
SPEC = os.path.join(PARTS, 'prompt_spec.json')

# 只保留引导必需的 USB 项与两个小项；boot 单独做坏；无 env、无 system
KEEP = [('DDR', 'USB'), ('DDR_ENC', 'USB'), ('UBOOT', 'USB'), ('UBOOT_ENC', 'USB'),
        ('meson1', 'dtb'), ('platform', 'conf')]


def extract_items():
    p = parse(SRC)
    os.makedirs(PARTS, exist_ok=True)
    out = {}
    with open(SRC, 'rb') as f:
        for it in p['items']:
            if (it['name'], it['fmt']) not in KEEP:
                continue
            fn = os.path.join(PARTS, '%02d_%s_%s.bin' % (it['index'], it['name'], it['fmt']))
            f.seek(it['off'])
            left = it['size']
            with open(fn, 'wb') as o:
                while left:
                    b = f.read(min(left, 1 << 22))
                    if not b:
                        break
                    o.write(b)
                    left -= len(b)
            out[(it['name'], it['fmt'])] = fn
    return out


def make_bad_boot():
    """复制原版 boot 分区内容，把前 64 KiB 清零（保留长度不变）。"""
    raw = open(KERNEL, 'rb').read()
    if len(raw) < ZAP_LEN:
        raise SystemExit('kernel too small: %d' % len(raw))
    bad = bytearray(raw)
    bad[:ZAP_LEN] = b'\x00' * ZAP_LEN
    fn = os.path.join(PARTS, 'boot_bad.bin')
    open(fn, 'wb').write(bytes(bad))
    return fn, len(raw), hashlib.sha256(bytes(bad)).hexdigest()


def main():
    files = extract_items()
    bad_boot, boot_size, bad_sha = make_bad_boot()
    print('bad boot: %d B  sha256 %s' % (boot_size, bad_sha[:16]))

    items = []
    for name, fmt in KEEP:
        items.append({'name': name, 'fmt': fmt, 'size': os.path.getsize(files[(name, fmt)]),
                      'src': files[(name, fmt)]})
        if name == 'UBOOT_ENC':
            # boot 紧跟引导项，保持与原包一致的位置语义
            items.append({'name': 'boot', 'fmt': 'PARTITION', 'size': boot_size, 'src': bad_boot})
            items.append({'name': 'boot', 'fmt': 'VERIFY', 'size': 48})
    # 注意：meson1/platform 在 boot 之后
    ordered = []
    for it in items:
        ordered.append(it)

    # 尺寸一致性：除 boot 外都必须与源包对应项同尺寸
    v3 = {it['name']: it for it in parse(SRC)['items'] if it['fmt'] != 'VERIFY'}
    for it in ordered:
        if it['fmt'] == 'VERIFY' or it['name'] == 'boot':
            continue
        assert it['size'] == v3[it['name']]['size'], 'size mismatch %s' % it['name']

    os.makedirs(PARTS, exist_ok=True)
    json.dump({'items': ordered}, open(SPEC, 'w', encoding='utf-8'))
    if os.path.exists(DST):
        os.remove(DST)
    cmd_build(SPEC, DST)

    p2, res = verify(DST)
    bad = [r for r in res if not r[1]]
    for name, ok, detail in res:
        if not ok:
            print('FAIL  %-30s %s' % (name, detail))
    print('%d checks, %d FAIL' % (len(res), len(bad)))
    assert not bad

    names = [(it['name'], it['fmt']) for it in p2['items']]
    assert ('env', 'PARTITION') not in names, 'env must be absent'
    assert ('system', 'PARTITION') not in names, 'system must be absent'
    print('items: %d (no env, no system, boot=bad)' % len(names))
    print('OK: %s  %d B (%.1f MiB)' % (DST, os.path.getsize(DST), os.path.getsize(DST) / 1048576))
    print('sha256 %s' % hashlib.sha256(open(DST, 'rb').read()).hexdigest())
    return 0


if __name__ == '__main__':
    sys.exit(main())
