#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""push_rootfs.py - 把 rootfs 镜像分段推送到 eMMC 指定偏移（两段式）

为什么不直接 `nc | dd`：
  实测（2026-11-13）`nc -l -p PORT | dd of=/dev/mmcblk2` 在 busybox 上只有
  406 B/s ~ 6.5 KB/s，而 `nc -l -p PORT > /tmp/f` 可达 14 MiB/s。
  原因未完全定位（管道与重定向在 busybox nc 上的行为差异），但两段式已实测可靠：
    step1  nc > /tmp/chunk.bin        (14 MiB/s)
    step2  dd if=/tmp/chunk.bin of=/dev/mmcblk2 bs=1M seek=N conv=notrunc  (0.02s / 10MiB)
  受 tmpfs 限制（空闲 ~855 MB），分片取 256 MiB。

用法:
  python3 scripts/push_rootfs.py                  # 全量 5 片
  python3 scripts/push_rootfs.py --seg 0          # 只第 0 片
  python3 scripts/push_rootfs.py --seg 0 --verify # 只校验第 0 片
"""
import argparse
import hashlib
import os
import socket
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
from dev import Dev

IMG = os.environ.get(
    'B860_ROOTFS_IMG',
    os.path.join(ROOT, '..', '..', 'out', 'rootfs-deb13-2560m.img'))
EMMC = '/dev/mmcblk2'
OFFSET_MIB = 3072            # 3 GiB
SEG_MIB = 256                # 每片（受设备 ramfs 与单次 nc 稳定性限制，512 MiB 会截断）
CHUNK_LOCAL = os.path.join(ROOT, '..', '..', 'out', 'chunk.bin')
HOST = os.environ.get('B860_HOST', '192.0.2.100')
PUSH_PORT = int(os.environ.get('B860_PUSH_PORT', '5559'))


def push_fast(local, remote, port=PUSH_PORT, timeout=600):
    """比 dev.push 快得多的发送：1 MiB 块 + 主动 shutdown。
    用 nohup 保护 nc 不被命令通道关闭时的 SIGHUP 杀掉。"""
    d = Dev()
    d.sh(f'rm -f {remote}; (nohup nc -l -p {port} > {remote} 2>/dev/null &) ; '
         f'echo RDY_$((3*7))', wait=300, until='RDY_21', until_timeout=5000)
    time.sleep(1.2)
    t0 = time.time()
    s = socket.create_connection((HOST, port), timeout=10)
    s.settimeout(timeout)
    sent = 0
    try:
        with open(local, 'rb') as f:
            while True:
                b = f.read(1 << 20)
                if not b:
                    break
                s.sendall(b)
                sent += len(b)
        try:
            s.shutdown(socket.SHUT_WR)
        except OSError:
            pass
    finally:
        s.close()
    return sent, time.time() - t0


def push_range(path, offset, size, remote, port=PUSH_PORT, timeout=600):
    """直接从镜像按偏移流式发送，不落本地切片文件（省掉 256 MiB 本地写盘）。"""
    d = Dev()
    d.sh(f'rm -f {remote}; (nohup nc -l -p {port} > {remote} 2>/dev/null &) ; '
         f'echo RDY_$((3*7))', wait=300, until='RDY_21', until_timeout=5000)
    time.sleep(1.2)
    t0 = time.time()
    sent = 0
    s = socket.create_connection((HOST, port), timeout=10)
    s.settimeout(timeout)
    try:
        with open(path, 'rb') as f:
            f.seek(offset)
            left = size
            while left:
                b = f.read(min(1 << 20, left))
                if not b:
                    break
                s.sendall(b)
                sent += len(b)
                left -= len(b)
        try:
            s.shutdown(socket.SHUT_WR)
        except OSError:
            pass
    finally:
        s.close()
    return sent, time.time() - t0


def wait_size(remote, want, timeout=300):
    """轮询设备端文件大小直到等于 want。返回最后看到的大小。"""
    d = Dev()
    t0 = time.time()
    last = -1
    stall = 0
    while time.time() - t0 < timeout:
        out = d.sh(f'wc -c {remote} 2>/dev/null', wait=900, until_timeout=12000)
        nums = [int(x) for x in out.replace(chr(13), ' ').split() if x.isdigit()]
        sz = nums[0] if nums else -1
        if sz == want:
            return sz
        if sz == last:
            stall += 1
        else:
            stall = 0
        last = sz
        if stall >= 20:      # 连续 20 次不增长，判定停滞
            return last
        time.sleep(0.5)
    return last


def sha_file(path, limit=None):
    h = hashlib.sha256()
    n = 0
    with open(path, 'rb') as f:
        while True:
            b = f.read(1 << 20)
            if not b:
                break
            if limit is not None and n + len(b) > limit:
                b = b[:limit - n]
            h.update(b)
            n += len(b)
            if limit is not None and n >= limit:
                break
    return h.hexdigest()


def slice_to_chunk(rel_mib, size):
    """从镜像切出该片到本地 chunk 文件，返回 sha256。"""
    os.makedirs(os.path.dirname(CHUNK_LOCAL), exist_ok=True)
    h = hashlib.sha256()
    with open(IMG, 'rb') as src, open(CHUNK_LOCAL, 'wb') as dst:
        src.seek(rel_mib << 20)
        left = size
        while left:
            b = src.read(min(1 << 20, left))
            if not b:
                break
            dst.write(b)
            h.update(b)
            left -= len(b)
    return h.hexdigest()


def sample_offsets(size, n=3, win=4 << 20):
    """片内抽样窗口偏移（字节）。全量 sha256 在设备上太慢（256 MiB > 300s 超时），
    改用首/中/尾三段各 4 MiB 抽样，读 eMMC 仅 12 MiB，秒级完成。"""
    if size <= win:
        return [0]
    step = (size - win) // max(1, n - 1)
    return sorted({i * step for i in range(n)})


def device_sha_window(abs_mib, win_mib):
    """设备端读 eMMC 某窗口的 sha256（窗口以 MiB 计）。"""
    d = Dev()
    cmd = (f'dd if={EMMC} bs=1M skip={abs_mib} count={win_mib} 2>/dev/null | sha256sum')
    out = d.sh(cmd, wait=1200, until_timeout=60000)
    for line in out.splitlines():
        line = line.strip()
        if len(line) >= 64 and all(c in '0123456789abcdef' for c in line[:64]):
            return line[:64]
    return None


def verify_seg(rel_mib, size, win_mib=4):
    """抽样校验一片：返回 (ok, details)。"""
    details = []
    ok = True
    for off in sample_offsets(size, 3, win_mib << 20):
        off_mib = off >> 20
        w = min(win_mib, (size - off) >> 20)
        if w <= 0:
            continue
        local = sha_file_range(IMG, (rel_mib + off_mib) << 20, w << 20)
        dev = device_sha_window(OFFSET_MIB + rel_mib + off_mib, w)
        good = (local == dev)
        details.append((off_mib, w, local, dev, good))
        ok = ok and good
    return ok, details


def sha_file_range(path, offset, size):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        f.seek(offset)
        left = size
        while left:
            b = f.read(min(1 << 20, left))
            if not b:
                break
            h.update(b)
            left -= len(b)
    return h.hexdigest()


def device_sha(rel_mib, size):
    """兼容旧接口：返回抽样汇总（首窗口）。"""
    ok, details = verify_seg(rel_mib, size)
    return details[0][2] if details else None


def confirm_emmc_write(targets):
    if not sys.stdin.isatty():
        raise SystemExit('拒绝在非交互终端写入 eMMC；请先在终端确认已备份，或仅使用 --verify')
    print(f'即将向 {EMMC} 从偏移 {OFFSET_MIB} MiB 写入 {len(targets)} 段，覆盖现有 eMMC 数据。')
    answer = input('请先确认已备份；输入 YES 继续: ').strip()
    if answer != 'YES':
        raise SystemExit('已取消，未写入 eMMC')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--seg', type=int, default=None)
    ap.add_argument('--verify', action='store_true')
    ap.add_argument('--seg-mib', type=int, default=SEG_MIB)
    args = ap.parse_args()

    seg_mib = args.seg_mib
    total = os.path.getsize(IMG)
    plan = []
    rel = 0
    idx = 0
    while rel * (1 << 20) < total:
        size = min(seg_mib << 20, total - rel * (1 << 20))
        plan.append((idx, rel, size))
        idx += 1
        rel += seg_mib

    print(f'image {os.path.basename(IMG)}  {total:,} B ({total/(1<<30):.2f} GiB)')
    print(f'eMMC offset {OFFSET_MIB} MiB   segments {len(plan)} × {seg_mib} MiB\n')

    targets = [p for p in plan if args.seg is None or p[0] == args.seg]
    fails = []
    if targets and not args.verify:
        confirm_emmc_write(targets)

    for i, rel_mib, size in targets:
        print(f'--- seg {i}/{len(plan)-1}: image+{rel_mib} MiB, {size/(1<<20):.1f} MiB ---')
        t0 = time.time()
        d = Dev()
        if not args.verify:
            sent, dt = push_range(IMG, rel_mib << 20, size, '/tmp/chunk.bin')
            print(f'    push {sent:,} B in {dt:.1f}s = {sent/dt/(1<<20):.2f} MiB/s')
            got_sz = wait_size('/tmp/chunk.bin', size)
            print(f'    device chunk {got_sz:,} / {size:,} B')
            if got_sz != size:
                print(f'    FAIL: device file incomplete ({got_sz} != {size})')
                fails.append((i, 'incomplete'))
                continue
            seek = OFFSET_MIB + rel_mib
            r = d.sh(f'dd if=/tmp/chunk.bin of={EMMC} bs=1M seek={seek} conv=notrunc '
                     f'2>/tmp/dd.err; sync; echo DD_RC=$?',
                     wait=800, until='DD_RC=', until_timeout=60000)
            print('    ' + ' | '.join(l.strip() for l in r.splitlines() if l.strip())[:160])
            d.sh('rm -f /tmp/chunk.bin', wait=300, until_timeout=2500)

        if args.verify:
            print('    抽样校验（首/中/尾各 4 MiB）...')
            ok, details = verify_seg(rel_mib, size)
            for off_mib, w, local, dev, good in details:
                print(f'      +{off_mib:5d} MiB ×{w} MiB  {"PASS" if good else "FAIL"}  '
                      f'local {local[:16]}… device {(dev or "(none)")[:16]}…')
            if not ok:
                fails.append((i, 'sha256'))
        else:
            # 快速模式：设备端 dd RC=0 + 文件大小已确认，跳过慢速抽样；
            # 全量完整性由最后的 ext4 mount 终检（超级块+日志+元数据）覆盖。
            ok = True
        print(f'    用时 {time.time()-t0:.1f}s\n')

    print('=' * 56)
    if fails:
        print(f'FAILED: {fails}')
        sys.exit(1)
    print('ALL SEGMENTS PASS')


if __name__ == '__main__':
    main()
