#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_v4_rgbfix.py — v4 = v3 + 修正版 env（RGB 输出 + OSD 1080p）

只改 4 个 env 变量（其余 69 个原样、顺序不变）：
  display_width  720    -> 1920   (osd open 满屏)
  display_height 576    -> 1080
  outputmode     576cvbs-> 1080p60hz
  init_display   在 vout output 1080p60hz 之后插入 hdmitx output 1080p60hz,8bits,rgb
                 (HDMI TX 锁 RGB 4:4:4 —— 颜色偏色的根治)

机制依据（全部实锤）：
  - 流程 preboot = run init_display; run storeargs; → env 被采纳（HDMIINIT_MARKER/DSH_AUTOBOOT 是 echo）
  - v24 实锤：包里 env item（download store env）落盘即生效
  - 0x38000000 裸写无效：store 逻辑 env 分区 ≠ 裸物理地址（分区表变化后挪位）

产物：out/batocera-2.1t/B860AV21T_v4_arm64_20261113_GA.img（与 v3 同尺寸，含 system=rootfs 恢复）
"""
import hashlib
import os
import shutil
import struct
import sys
import zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from aml import parse, verify, file_crc  # noqa: E402

SRC = os.environ.get('B860_V3_IMG', 'out/B860AV21T_v3_arm64_20261111_GA.img')
DST = os.environ.get('B860_V4_IMG', 'out/B860AV21T_v4_arm64_20261113_GA.img')
ENV_SRC = os.environ.get('B860_ENV_V3', 'out/env_item_v3.bin')
ENV_NEW = os.environ.get('B860_ENV_V4', 'out/env_item_v4.bin')

CHANGES = {
    'display_width': '1920',
    'display_height': '1080',
    'outputmode': '1080p60hz',
}
INIT_DISPLAY_OLD = ('echo HDMIINIT_MARKER;hdmitx hpd;vout output 1080p60hz;'
                    'osd open;osd clear;bmp scale')
INIT_DISPLAY_NEW = ('echo HDMIINIT_MARKER;hdmitx hpd;vout output 1080p60hz;'
                    'hdmitx output 1080p60hz,8bits,rgb;'
                    'osd open;osd clear;bmp scale')


def parse_vars(blob):
    data = blob[4:]
    i, out = 0, []
    while i < len(data):
        j = data.find(b'\x00', i)
        if j < 0:
            break
        s = data[i:j]
        if not s:
            break
        k, _, v = s.partition(b'=')
        out.append((k.decode(), v.decode('latin1')))
        i = j + 1
    return out


def build_blob(vars_):
    body = b''
    for k, v in vars_:
        body += b'%s=%s\x00' % (k.encode(), v.encode('latin1'))
    body += b'\x00'                       # env 结束双 NUL
    # CRC 覆盖 blob[4:65536] 全部（含补零），与原包实测一致
    body += b'\x00' * (65536 - 4 - len(body))
    crc = zlib.crc32(body) & 0xFFFFFFFF
    blob = struct.pack('<I', crc) + body
    assert len(blob) == 65536
    return blob


def main():
    blob_old = open(ENV_SRC, 'rb').read()
    vars_ = parse_vars(blob_old)
    assert len(vars_) == 73, 'var count %d' % len(vars_)

    changed = []
    out = []
    for k, v in vars_:
        if k == 'init_display':
            assert v == INIT_DISPLAY_OLD, 'init_display mismatch:\n  %s' % v
            v = INIT_DISPLAY_NEW
            changed.append(k)
        elif k in CHANGES:
            changed.append('%s: %s -> %s' % (k, v, CHANGES[k]))
            v = CHANGES[k]
        out.append((k, v))

    blob_new = build_blob(out)
    open(ENV_NEW, 'wb').write(blob_new)
    # 自校验：CRC 与解析回读
    assert struct.unpack('<I', blob_new[:4])[0] == zlib.crc32(blob_new[4:]) & 0xFFFFFFFF
    rt = parse_vars(blob_new)
    d = dict(rt)
    assert len(rt) == 73
    assert d['display_width'] == '1920' and d['display_height'] == '1080'
    assert d['outputmode'] == '1080p60hz'
    assert 'hdmitx output 1080p60hz,8bits,rgb' in d['init_display']
    assert d['storeargs'] == dict(parse_vars(blob_old))['storeargs'], 'storeargs changed!'
    for c in changed:
        print('  changed:', c)
    print('  env blob rebuilt: 65536 B, crc=0x%08x, 73 vars OK' %
          struct.unpack('<I', blob_new[:4])[0])

    # 组 v4 包：v3 复制 + env item 原地替换 + 重算头 CRC
    if os.path.exists(DST):
        os.remove(DST)
    shutil.copyfile(SRC, DST)
    p = parse(DST)
    env = [it for it in p['items'] if it['name'] == 'env'][0]
    with open(DST, 'r+b') as f:
        f.seek(env['off'])
        f.write(blob_new)
        f.flush()
        crc = file_crc(DST) ^ 0xFFFFFFFF
        f.seek(0)
        f.write(struct.pack('<I', crc))
        f.flush()
        os.fsync(f.fileno())

    p2, res = verify(DST)
    bad = [r for r in res if not r[1]]
    for name, ok, detail in res:
        if not ok:
            print('FAIL  %-30s %s' % (name, detail))
    print('%d checks, %d FAIL' % (len(res), len(bad)))
    assert not bad

    # 内容比对：除 env item 外全部与 v3 一致
    src_p = parse(SRC)
    smap = {(it['name'], it['fmt']): it for it in src_p['items']}
    with open(SRC, 'rb') as fa, open(DST, 'rb') as fb:
        for it in p2['items']:
            if it['name'] == 'env':
                continue
            s = smap[(it['name'], it['fmt'])]
            fa.seek(s['off']); fb.seek(it['off'])
            n = it['size']
            while n:
                k = min(n, 1 << 22)
                if fa.read(k) != fb.read(k):
                    print('MISMATCH %s %s' % (it['name'], it['fmt']))
                    return 1
                n -= k
    print('content compare vs v3: identical except env item')
    print('OK: %s  %d B' % (DST, os.path.getsize(DST)))
    print('sha256 %s' % hashlib.sha256(open(DST, 'rb').read()).hexdigest())
    return 0


if __name__ == '__main__':
    sys.exit(main())
