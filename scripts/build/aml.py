#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""aml.py - Amlogic AML v2 烧录包的解析 / 校验 / 组装（本项目自建）

包结构（实测反推，见 audit/aml-format.md）：
  offset 0   : u32 magic 0x4f624ed3 ("\xd3NbO") | u32 version=2 | u32 crc32(file[4:])
               u32 ? | u32 ? | u32 ? | u32 count
  offset 64  : count × 576 B item 表
               item: u32 index @0 | u64 file_off @16 | u64 size @24
                     char[64] fmt @32 ("USB"/"PARTITION"/"VERIFY"/"dtb"/"conf")
                     char[32] name @0x120
  其后       : 各 item 的原始数据（顺序排列，无对齐要求）

VERIFY 项内容 = 同名 PARTITION 数据的 SHA1(20B) + 28B 零填充。

用法：
  python aml.py info    <img>
  python aml.py verify  <img>
  python aml.py extract <img> <outdir>
  python aml.py build   <spec.json> <out.img>
"""
import hashlib
import json
import os
import struct
import sys
import zlib

ITEM = 576
TAG = 0x27b51956            # 头偏移 8 的常量，所有已知包一致（实测 7 个包）


def parse(path):
    with open(path, 'rb') as f:
        head = f.read(64)
        crc, ver, tag = struct.unpack_from('<III', head, 0)
        cnt = struct.unpack_from('<I', head, 24)[0]
        items = []
        for i in range(cnt):
            b = f.read(ITEM)
            if len(b) < ITEM:
                raise SystemExit('item 表截断于第 %d 项' % i)
            idx = struct.unpack_from('<I', b, 0)[0]
            off, size = struct.unpack_from('<QQ', b, 16)
            fmt = bytes(b[32:96]).split(b'\x00')[0].decode('latin1')
            name = bytes(b[0x120:0x140]).split(b'\x00')[0].decode('latin1')
            items.append(dict(index=idx, off=off, size=size, fmt=fmt, name=name))
    return dict(path=path, crc=crc, version=ver, tag=tag, count=cnt,
                size=os.path.getsize(path), items=items)


def file_crc(path):
    crc = 0
    with open(path, 'rb') as f:
        f.seek(4)
        while True:
            c = f.read(1 << 24)
            if not c:
                break
            crc = zlib.crc32(c, crc)
    return crc & 0xFFFFFFFF


def verify(path, expect=None):
    p = parse(path)
    res = []

    def chk(name, ok, detail=''):
        res.append((name, bool(ok), detail))

    chk('tag 常量', p['tag'] == TAG, '0x%08x' % p['tag'])
    chk('version==2', p['version'] == 2, str(p['version']))
    chk('item 数与表一致', p['count'] == len(p['items']), str(p['count']))
    real = file_crc(path) ^ 0xFFFFFFFF
    chk('头 CRC = crc32(file[4:])^0xFFFFFFFF', p['crc'] == real,
        '%08x/%08x' % (p['crc'], real))

    hdr_end = 64 + ITEM * p['count']
    last = hdr_end
    for it in p['items']:
        ok = it['off'] >= hdr_end and it['off'] + it['size'] <= p['size']
        chk('item[%d] %-10s 边界' % (it['index'], it['name']), ok,
            'off=0x%X size=%d' % (it['off'], it['size']))
        last = max(last, it['off'] + it['size'])
        if it['fmt'] == 'VERIFY':
            prev = [x for x in p['items'] if x['name'] == it['name']
                    and x['fmt'] != 'VERIFY' and x['off'] < it['off']]
            if prev:
                src = prev[-1]
                h = hashlib.sha1()
                with open(path, 'rb') as f:
                    f.seek(src['off'])
                    left = src['size']
                    while left:
                        b = f.read(min(left, 1 << 22))
                        if not b:
                            break
                        h.update(b)
                        left -= len(b)
                with open(path, 'rb') as f:
                    f.seek(it['off'])
                    blob = f.read(it['size'])
                want = b'sha1sum ' + h.hexdigest().encode()
                chk('VERIFY %s = sha1sum 文本' % it['name'], blob[:len(want)] == want,
                    blob[:20].decode('latin1', 'replace'))
    chk('无越界空洞', last <= p['size'], 'max_end=0x%X file=%d' % (last, p['size']))

    if expect:
        for k, v in expect.items():
            got = {x['name']: x for x in p['items']}.get(k)
            chk('存在 %s' % k, got is not None)
            if got and v.get('size'):
                chk('%s size==%d' % (k, v['size']), got['size'] == v['size'],
                    str(got['size']))
    return p, res


def cmd_info(img):
    p = parse(img)
    print('%s  %d B  crc=%08x ver=%d tag=%08x items=%d'
          % (img, p['size'], p['crc'], p['version'], p['tag'], p['count']))
    for it in p['items']:
        print('  [%2d] %-10s %-9s off=0x%09X end=0x%09X size=%10d (%.1f MiB)'
              % (it['index'], it['name'], it['fmt'], it['off'],
                 it['off'] + it['size'], it['size'], it['size'] / 1048576))


def cmd_verify(img):
    p, res = verify(img)
    bad = 0
    for name, ok, detail in res:
        if not ok:
            bad += 1
            print('FAIL  %-28s %s' % (name, detail))
    print('%d 项检查，%d FAIL，%d PASS' % (len(res), bad, len(res) - bad))
    return 1 if bad else 0


def cmd_extract(img, outdir):
    p = parse(img)
    os.makedirs(outdir, exist_ok=True)
    with open(img, 'rb') as f:
        for it in p['items']:
            fn = os.path.join(outdir, '%02d_%s_%s.bin'
                              % (it['index'], it['name'],
                                 it['fmt'].lower()))
            f.seek(it['off'])
            left = it['size']
            with open(fn, 'wb') as o:
                while left:
                    b = f.read(min(left, 1 << 22))
                    if not b:
                        break
                    o.write(b)
                    left -= len(b)
            print('  %-40s %d B' % (os.path.basename(fn), it['size']))


def cmd_build(spec_path, out_path):
    spec = json.load(open(spec_path, encoding='utf-8'))
    items = spec['items']
    n = len(items)
    off = 64 + ITEM * n

    # 先算偏移
    for it in items:
        it['off'] = off
        off += it['size']

    with open(out_path, 'wb') as o:
        o.write(b'\x00' * (64 + ITEM * n))          # 占位
        for it in items:
            src = it.get('src')
            size = it['size']
            written = 0
            if src == 'zeros' or src is None:
                chunk = b'\x00' * (1 << 22)
                while written < size:
                    k = min(len(chunk), size - written)
                    o.write(chunk[:k])
                    written += k
            else:
                with open(src, 'rb') as f:
                    while written < size:
                        b = f.read(min(1 << 22, size - written))
                        if not b:
                            break
                        o.write(b)
                        written += len(b)
                if written < size:
                    o.write(b'\x00' * (size - written))
                    print('  注意：%s 实际 %d B，补零到 %d'
                          % (it['name'], written, size))
        o.flush()
        os.fsync(o.fileno())

    # VERIFY 项回填
    with open(out_path, 'r+b') as f:
        for it in items:
            if it['fmt'] != 'VERIFY':
                continue
            prev = [x for x in items if x['name'] == it['name']
                    and x['fmt'] != 'VERIFY' and x['off'] < it['off']][-1]
            h = hashlib.sha1()
            f.seek(prev['off'])
            left = prev['size']
            while left:
                b = f.read(min(left, 1 << 22))
                if not b:
                    break
                h.update(b)
                left -= len(b)
            f.seek(it['off'])
            # 实测原厂包 VERIFY 内容是 ASCII "sha1sum <40 hex>"，不是裸 20 字节摘要
            txt = b'sha1sum ' + h.hexdigest().encode()
            f.write(txt + b'\x00' * (it['size'] - len(txt)))
            print('  VERIFY %s = sha1sum %s' % (it['name'], h.hexdigest()))

    # item 表
    with open(out_path, 'r+b') as f:
        for i, it in enumerate(items):
            b = bytearray(ITEM)
            struct.pack_into('<I', b, 0, i)
            struct.pack_into('<QQ', b, 16, it['off'], it['size'])
            b[32:32 + len(it['fmt'])] = it['fmt'].encode()
            b[0x120:0x120 + len(it['name'])] = it['name'].encode()
            f.seek(64 + ITEM * i)
            f.write(b)
        # 先把除 CRC 外的头字段写全，再算 CRC —— CRC 覆盖 file[4:]，含 ver/tag/count
        f.seek(4)
        f.write(struct.pack('<II', 2, TAG))
        f.seek(24)
        f.write(struct.pack('<I', n))
        f.flush()
        crc = file_crc(out_path) ^ 0xFFFFFFFF
        f.seek(0)
        f.write(struct.pack('<I', crc))
        f.flush()
        os.fsync(f.fileno())

    print('built %s  %d B  crc=%08x' % (out_path, os.path.getsize(out_path), crc))
    print('sha256 %s' % hashlib.sha256(open(out_path, 'rb').read()).hexdigest())
    return 0


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    cmd = sys.argv[1]
    if cmd == 'info':
        return cmd_info(sys.argv[2]) or 0
    if cmd == 'verify':
        return cmd_verify(sys.argv[2])
    if cmd == 'extract':
        return cmd_extract(sys.argv[2], sys.argv[3]) or 0
    if cmd == 'build':
        return cmd_build(sys.argv[2], sys.argv[3])
    print('未知命令', cmd)
    return 2


if __name__ == '__main__':
    sys.exit(main())
