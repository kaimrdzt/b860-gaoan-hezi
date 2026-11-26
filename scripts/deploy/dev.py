#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dev.py - 设备通道（本项目自建，替代旧 ncmd/push_file）

设备侧常驻：`nc -lk -p 2323 -e /bin/sh`（由 initramfs 的 /init 起）。
本模块提供三件事：
  sh(cmd)            执行命令并返回输出（用算术展开做执行证据，避免回显假阳性）
  pull(remote, local)设备侧 `nc -l -p PORT < remote`，PC 主动连过去收
  push(local, remote)设备侧 `nc -l -p PORT > remote`，PC 主动连过去发
  sha256(remote)     设备侧算 sha256（busybox 有 sha256sum）

注意：本文件不复用 scripts/ 下任何旧实现。
"""
import hashlib
import os
import socket
import time

HOST = os.environ.get('B860_HOST', '192.0.2.100')   # 按实际盒子 IP 设置
SHELL_PORT = int(os.environ.get('B860_SHELL_PORT', '2323'))
PULL_PORT = 5558
PUSH_PORT = int(os.environ.get('B860_PUSH_PORT', '5559'))


class Dev:
    def __init__(self, host=HOST, port=SHELL_PORT, quiet=0.35):
        self.host = host
        self.port = port
        self.quiet = quiet

    # ---------- 基础 ----------
    def _conn(self, timeout=8):
        s = socket.create_connection((self.host, self.port), timeout=timeout)
        s.settimeout(0.3)
        return s

    def sh(self, cmd, wait=None, until=None, until_timeout=0):
        """执行一条命令，返回 (输出文本)。wait=静默毫秒。"""
        wait = self.quiet if wait is None else wait / 1000.0
        s = self._conn()
        out = bytearray()

        def drain(ms):
            end = time.time() + ms
            while time.time() < end:
                try:
                    d = s.recv(65536)
                    if not d:
                        break
                    out.extend(d)
                    if until and until.encode() in out:
                        return True
                except socket.timeout:
                    pass
                except OSError:
                    break
            return False

        drain(0.25)
        out.clear()
        s.sendall(cmd.encode() + b'\n')
        t_end = time.time() + (until_timeout / 1000.0 if until_timeout else 60)
        while time.time() < t_end:
            if drain(wait):
                break
            if until and until.encode() in out:
                break
        s.close()
        return out.decode('utf-8', 'replace')

    def alive(self):
        try:
            r = self.sh('echo CHAN_$((6*7))_OK', wait=800, until='CHAN_42_OK',
                        until_timeout=4000)
            return 'CHAN_42_OK' in r
        except OSError:
            return False

    # ---------- 文件 ----------
    def pull(self, remote, local, port=PULL_PORT, size=None):
        """设备侧起 nc 监听并把 remote 发过来；PC 连过去收。"""
        # 先让设备进入监听（后台），再连
        self.sh('(nc -l -p %d < %s >/dev/null 2>&1 &) ; echo PULL_READY_$((3*7))'
                % (port, remote), wait=300, until='PULL_READY_21', until_timeout=4000)
        got = 0
        t0 = time.time()
        with socket.create_connection((self.host, port), timeout=10) as s:
            s.settimeout(30)
            with open(local, 'wb') as f:
                while True:
                    try:
                        b = s.recv(65536)
                    except socket.timeout:
                        break
                    if not b:
                        break
                    f.write(b)
                    got += len(b)
        return got, time.time() - t0

    def push(self, local, remote, port=PUSH_PORT):
        """设备侧 nc 监听并重定向到 remote；PC 连过去发。"""
        self.sh('(nc -l -p %d > %s 2>/dev/null &) ; echo PUSH_READY_$((3*7))'
                % (port, remote), wait=300, until='PUSH_READY_21', until_timeout=4000)
        sent = 0
        t0 = time.time()
        with socket.create_connection((self.host, port), timeout=10) as s:
            s.settimeout(30)
            with open(local, 'rb') as f:
                while True:
                    b = f.read(65536)
                    if not b:
                        break
                    s.sendall(b)
                    sent += len(b)
        return sent, time.time() - t0

    def sha256(self, remote):
        out = self.sh('sha256sum %s 2>/dev/null | cut -c1-64' % remote,
                      wait=600, until_timeout=8000)
        for tok in out.split():
            if len(tok) == 64 and all(c in '0123456789abcdef' for c in tok):
                return tok
        return ''


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        while True:
            b = f.read(1 << 20)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


if __name__ == '__main__':
    import sys
    d = Dev()
    if len(sys.argv) < 2:
        print('alive:', d.alive())
        print(d.sh('uname -r; cat /mnt/r/tmp/.mode 2>/dev/null'))
    elif sys.argv[1] == 'sh':
        print(d.sh(' '.join(sys.argv[2:])))
    elif sys.argv[1] == 'pull':
        n, dt = d.pull(sys.argv[2], sys.argv[3])
        print('pulled %d B in %.1fs  sha256=%s' % (n, dt, sha256_file(sys.argv[3])))
    elif sys.argv[1] == 'push':
        n, dt = d.push(sys.argv[2], sys.argv[3])
        print('pushed %d B in %.1fs' % (n, dt))
