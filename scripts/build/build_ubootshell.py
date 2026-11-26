#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_ubootshell.py — 生成"进 U-Boot 提示符"救援包

机制（debian 时代三次实锤，见 .workbuddy/memory/2026-11-05.md §17:31/18:38、11-06 §08:30）：
  env 分区被擦除/无效 → U-Boot 静默回退默认 env → 启动失败 → 停在 gxl_p211_v1# 提示符
  （v22: "boot system norm failed -> gxl_p211_v1#"；v22e: "try boot safe! -> gxl_p211_v1#"；
   11-06: "store erase partition env + reboot -> 停在提示符"）

包内容：v3 的 DDR/DDR_ENC/UBOOT/UBOOT_ENC + 好内核(boot+VERIFY) + meson1(dtb) + platform(conf)。
  不含 env 项  → 烧录的 amlmmc erase 会把 env 分区擦空，且不回写 → 提示符必然出现
  不含 system  → 反正会被整片擦除；rootfs 由后续 v3 全量恢复
  内核用原版   → 若默认 env 恰好能引导，则落到 initramfs shell（同样是救援）

产物：out/batocera-2.1t/B860AV21T_UBOOTSHELL_arm64_20261113.img（~11 MiB）
"""
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from aml import parse, verify, cmd_build  # noqa: E402

SRC = os.environ.get('B860_V3_IMG', 'out/B860AV21T_v3_arm64_20261111_GA.img')
KERNEL = os.environ.get('B860_V3_KERNEL', 'out/boot_v3_kernel.bin')
DST = os.environ.get('B860_UBOOTSHELL_IMG', 'out/B860AV21T_UBOOTSHELL_arm64_20261113.img')
PARTS = os.environ.get('B860_PARTS_DIR', 'out/parts_rescue')
SPEC = os.environ.get('B860_UBOOTSHELL_SPEC', 'out/ubootshell_spec.json')

# 保留项：无 env、无 system
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
                    o.write(b)
                    left -= len(b)
            out[(it['name'], it['fmt'])] = fn
    return out


def main():
    files = extract_items()
    boot_size = os.path.getsize(KERNEL)

    items = [
        {'name': 'DDR',      'fmt': 'USB',       'size': os.path.getsize(files[('DDR', 'USB')]),       'src': files[('DDR', 'USB')]},
        {'name': 'DDR_ENC',  'fmt': 'USB',       'size': os.path.getsize(files[('DDR_ENC', 'USB')]),   'src': files[('DDR_ENC', 'USB')]},
        {'name': 'UBOOT',    'fmt': 'USB',       'size': os.path.getsize(files[('UBOOT', 'USB')]),     'src': files[('UBOOT', 'USB')]},
        {'name': 'UBOOT_ENC', 'fmt': 'USB',      'size': os.path.getsize(files[('UBOOT_ENC', 'USB')]), 'src': files[('UBOOT_ENC', 'USB')]},
        {'name': 'boot',     'fmt': 'PARTITION', 'size': boot_size, 'src': KERNEL},
        {'name': 'boot',     'fmt': 'VERIFY',    'size': 48},
        {'name': 'meson1',   'fmt': 'dtb',       'size': os.path.getsize(files[('meson1', 'dtb')]),    'src': files[('meson1', 'dtb')]},
        {'name': 'platform', 'fmt': 'conf',      'size': os.path.getsize(files[('platform', 'conf')]), 'src': files[('platform', 'conf')]},
    ]
    v3 = {it['name']: it for it in parse(SRC)['items'] if it['fmt'] != 'VERIFY'}
    for it in items:
        if it['fmt'] == 'VERIFY':
            continue
        assert it['size'] == v3[it['name']]['size'], \
            'size mismatch %s' % it['name']

    json.dump({'items': items}, open(SPEC, 'w', encoding='utf-8'))
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

    # 内容比对：全部项与 v3 一致（本包不含 env/system，boot 用原版内核 → 应全同）
    src_p = parse(SRC)
    smap = {(it['name'], it['fmt']): it for it in src_p['items']}
    with open(SRC, 'rb') as fa, open(DST, 'rb') as fb:
        for it in p2['items']:
            if (it['name'], it['fmt']) == ('boot', 'VERIFY'):
                continue    # sha1 与 v3 相同但位置不同，跳过字节比对（前面结构校验已覆盖）
            s = smap[(it['name'], it['fmt'])]
            fa.seek(s['off']); fb.seek(it['off'])
            n = it['size']
            while n:
                k = min(n, 1 << 22)
                if fa.read(k) != fb.read(k):
                    print('MISMATCH %s %s' % (it['name'], it['fmt']))
                    return 1
                n -= k
    print('content compare vs v3: all identical')
    print('OK: %s  %d B (%.1f MiB)' % (DST, os.path.getsize(DST),
                                       os.path.getsize(DST) / 1048576))
    print('sha256 %s' % hashlib.sha256(open(DST, 'rb').read()).hexdigest())
    print('items: %d (no env, no system)' % len(items))
    return 0


if __name__ == '__main__':
    sys.exit(main())
