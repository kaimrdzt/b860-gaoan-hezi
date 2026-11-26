#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_rescue_small.py — 精简版救援包（不含 1GB system 分区）

从 v3 抽取必需 item，内核用破坏版（前 64KB 清零），重新组包并校验：
  DDR / DDR_ENC / UBOOT / UBOOT_ENC   ← USB 项，烧录工具引导必需，原样保留
  boot(坏) + boot VERIFY              ← 整个方案的目标
  meson1(dtb) / platform(conf) / env  ← 小项，原样保留
不含 system(1GB)：烧完 rootfs 保持现状，自定义文件（gwctl/restore_regs 等）不丢。

产物：out/batocera-2.1t/B860AV21T_RESCUE_BADBOOT_arm64_20261113.img（~11.5MB）
"""
import hashlib
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from aml import parse, verify, cmd_build  # noqa: E402

SRC = os.environ.get('B860_V3_IMG', 'out/B860AV21T_v3_arm64_20261111_GA.img')
KERNEL = os.environ.get('B860_V3_KERNEL', 'out/boot_v3_kernel.bin')   # v3 原始内核（需先抽出）
DST = os.environ.get('B860_RESCUE_IMG', 'out/B860AV21T_RESCUE_BADBOOT_arm64_20261113.img')
PARTS = os.environ.get('B860_PARTS_DIR', 'out/parts_rescue')
ZAP_LEN = 65536
SPEC = os.environ.get('B860_RESCUE_SPEC', 'out/rescue_spec.json')

# --restore 模式：内核不破坏，仅恢复 boot 分区（不动 system/rootfs）
RESTORE = '--restore' in sys.argv
if RESTORE:
    DST = 'out/batocera-2.1t/B860AV21T_BOOTRESTORE_arm64_20261113.img'

# 需要保留的 item（按原顺序，system 除外）
KEEP = [('DDR', 'USB'), ('DDR_ENC', 'USB'), ('UBOOT', 'USB'), ('UBOOT_ENC', 'USB'),
        ('meson1', 'dtb'), ('platform', 'conf'), ('env', 'PARTITION')]


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
            print('  extract %-12s %-9s %9d B -> %s' % (it['name'], it['fmt'], it['size'], fn))
    return out


def make_bad_kernel():
    bad = os.path.join(PARTS, 'boot_bad.bin')
    shutil.copyfile(KERNEL, bad)
    if not RESTORE:
        with open(bad, 'r+b') as f:
            f.seek(0)
            f.write(b'\x00' * ZAP_LEN)
        print('  boot_bad.bin: %d B, head %d bytes zeroed' % (os.path.getsize(bad), ZAP_LEN))
    else:
        print('  boot_restore.bin: %d B (intact kernel)' % os.path.getsize(bad))
    return bad


def main():
    files = extract_items()
    bad = make_bad_kernel()
    boot_size = os.path.getsize(KERNEL)

    items = [
        {'name': 'DDR',      'fmt': 'USB',       'size': os.path.getsize(files[('DDR', 'USB')]),       'src': files[('DDR', 'USB')]},
        {'name': 'DDR_ENC',  'fmt': 'USB',       'size': os.path.getsize(files[('DDR_ENC', 'USB')]),   'src': files[('DDR_ENC', 'USB')]},
        {'name': 'UBOOT',    'fmt': 'USB',       'size': os.path.getsize(files[('UBOOT', 'USB')]),     'src': files[('UBOOT', 'USB')]},
        {'name': 'UBOOT_ENC', 'fmt': 'USB',      'size': os.path.getsize(files[('UBOOT_ENC', 'USB')]), 'src': files[('UBOOT_ENC', 'USB')]},
        {'name': 'boot',     'fmt': 'PARTITION', 'size': boot_size, 'src': bad},
        {'name': 'boot',     'fmt': 'VERIFY',    'size': 48},
        {'name': 'meson1',   'fmt': 'dtb',       'size': os.path.getsize(files[('meson1', 'dtb')]),    'src': files[('meson1', 'dtb')]},
        {'name': 'platform', 'fmt': 'conf',      'size': os.path.getsize(files[('platform', 'conf')]), 'src': files[('platform', 'conf')]},
        {'name': 'env',      'fmt': 'PARTITION', 'size': os.path.getsize(files[('env', 'PARTITION')]), 'src': files[('env', 'PARTITION')]},
    ]
    # 与 v3 原 item 尺寸核对（防止抽取有误）
    v3 = {it['name']: it for it in parse(SRC)['items'] if it['fmt'] != 'VERIFY'}
    for it in items:
        if it['fmt'] == 'VERIFY':
            continue
        assert it['size'] == v3[it['name']]['size'], \
            'size mismatch %s: %d vs %d' % (it['name'], it['size'], v3[it['name']]['size'])

    json.dump({'items': items}, open(SPEC, 'w', encoding='utf-8'))
    if os.path.exists(DST):
        os.remove(DST)
    cmd_build(SPEC, DST)

    # 结构校验
    p2, res = verify(DST)
    bad_res = [r for r in res if not r[1]]
    for name, ok, detail in res:
        if not ok:
            print('FAIL  %-30s %s' % (name, detail))
    print('%d checks, %d FAIL' % (len(res), len(bad_res)))
    assert not bad_res, 'structure verify failed'

    # 确认内核头部状态
    pk = [it for it in p2['items'] if it['name'] == 'boot' and it['fmt'] == 'PARTITION'][0]
    with open(DST, 'rb') as f:
        f.seek(pk['off'])
        head = f.read(64)
    if RESTORE:
        assert head != b'\x00' * 64, 'kernel head should be intact'
        print('kernel head intact OK')
    else:
        assert head == b'\x00' * 64, 'kernel head not zeroed'
        print('kernel head zeroed OK')

    # 内容比对：boot 项前 64KB 之外、其余全部项必须与 v3 一致
    skipzap = 0 if RESTORE else ZAP_LEN
    src_p = parse(SRC)
    smap = {(it['name'], it['fmt']): it for it in src_p['items']}
    with open(SRC, 'rb') as fa, open(DST, 'rb') as fb:
        for it in p2['items']:
            if (it['name'], it['fmt']) == ('boot', 'VERIFY'):
                continue    # 有意不同：记录的是坏内核的 sha1
            s = smap[(it['name'], it['fmt'])]
            fa.seek(s['off']); fb.seek(it['off'])
            fa.read(skipzap); fb.read(skipzap)
            n = it['size'] - skipzap
            while n:
                k = min(n, 1 << 22)
                if fa.read(k) != fb.read(k):
                    print('MISMATCH %s %s' % (it['name'], it['fmt']))
                    return 1
                n -= k
    print('content compare vs v3: all identical (except intentional kernel zap)')

    print('OK: %s  %d B (%.1f MiB)' % (DST, os.path.getsize(DST),
                                       os.path.getsize(DST) / 1048576))
    print('sha256 %s' % hashlib.sha256(open(DST, 'rb').read()).hexdigest())
    return 0


if __name__ == '__main__':
    sys.exit(main())
