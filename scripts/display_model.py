#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""display_model.py —— 现行显示模型（2026-11-09 实机定案）

背景：这台盒子（GXLX2 / B860AV2.1-T）的 OSD 由 U-Boot 的 `bmp scale` 配好，
Linux 的 simple-framebuffer 只接管显存、从不重配 OSD，所以整套显示参数继承 U-Boot。

**真实参数（寄存器 + 白场实测双重确认）**
  * 画布像素格式 **24bpp**：W0 的 blk_mode = 0x07 (OSD_BLK_MODE_24)，stride 5760。
    （/dev/fb0 报 x8r8g8b8 是 DTB 里写的，与硬件块模式不一致，别被它带偏。）
  * 输出窗口 SCO 的**行数 = 值 × 3/8**：白场实测 2159 → 810 行（3/4 屏）、
    2880(0xB40) → 1080 行（满屏）。U-Boot 残留 0x11F(287) → 107 行（约 1/10 屏）。
  * 垂直相位步长 1:1 = **0x02000000**（2026-11-13 实机定案：0x01000000 实为 0.5 倍
    采样 —— 只取 540 行再放大 2 倍，现象为「只显示一半 / 8 段色带只出 4 段」）。
  * 水平相位步长 1:1 = 0x01000000（横向实测正确，未变）。
  * VSC_CTRL0 bit23 = VSC_PROG_INTERLACE，U-Boot 置位，须清零（0x01823124 → 0x01023124）。

**曾经的错误模型（全部作废）**
  * 「硬件按 K×5760 读行」——不成立。
  * 「画布是 32bpp，应写 7680」——不成立；写 32bpp 会因 stride 与块模式不匹配而花屏。

用法： python3 scripts/display_model.py --selftest
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

W, H = 1920, 1080
BPP = 3                          # 24bpp（与 OSD_BLK_MODE_24 一致）
STRIDE = W * BPP                 # 5760
FRAME_BYTES = STRIDE * H         # 6,220,800
CANVAS_OFF = 4 << 20
FB_RESERVED = 40 << 20

WIN_NUM, WIN_DEN = 3, 8          # 行数 = 值 × 3/8
SCO_V_FULL = 0xB40               # 2880 -> 1080 行
SCO_V_UBOOT = 0x11F              # 287  -> 107 行
SCO_H_FULL = 0xEFF

HW_VSC_CTRL0 = 0x01823124
VSC_CTRL0_FIXED = 0x01023124
PHASE_V_1_1 = 0x02000000      # 垂直：1:1（实测修正）
PHASE_H_1_1 = 0x01000000      # 水平：1:1

APPLIED = [
    ('SCO_H_START_END', 0x1DCA, 0x00000EFF),
    ('SCO_V_START_END', 0x1DCB, 0x00000B40),
    ('VSC_PHASE_STEP', 0x1DC0, PHASE_V_1_1),
    ('HSC_PHASE_STEP', 0x1DC3, PHASE_H_1_1),
    ('VSC_CTRL0', 0x1DC2, VSC_CTRL0_FIXED),
    ('VSC_INI_PHASE', 0x1DC1, 0x00000000),
]


def rows_of(value):
    return value * WIN_NUM // WIN_DEN


def _read(rel):
    try:
        with open(os.path.join(ROOT, rel), encoding='utf-8', errors='replace') as f:
            return f.read()
    except OSError:
        return ''


class Checker:
    def __init__(self):
        self.n = 0
        self.fail = 0

    def eq(self, name, got, want):
        self.n += 1
        ok = got == want
        if not ok:
            self.fail += 1
        print('  %s %-50s got=%r want=%r' % ('PASS' if ok else 'FAIL', name, got, want))

    def true(self, name, cond, extra=''):
        self.n += 1
        if not cond:
            self.fail += 1
            if extra:
                name = name + ' | ' + extra
        print('  %s %s' % ('PASS' if cond else 'FAIL', name))


def selftest():
    c = Checker()

    print('[1] 画布格式')
    c.eq('24bpp 行步长 = 1920*3', STRIDE, 5760)
    c.eq('一帧字节 = stride*1080', FRAME_BYTES, 6220800)
    c.eq('40MiB 预留足够', CANVAS_OFF + FRAME_BYTES <= FB_RESERVED, True)

    print('[2] 输出窗口编码（行数 = 值 × 3/8）')
    c.eq('U-Boot 残留 0x11F -> 107 行', rows_of(SCO_V_UBOOT), 107)
    c.eq('旧错误值 0x86F -> 809 行（≈3/4 屏）', rows_of(0x86F), 809)
    c.eq('现行 0xB40 -> 1080 行（满屏）', rows_of(SCO_V_FULL), 1080)
    c.eq('810/1080 = 3/4（与用户观察一致）', (810 * 4) // 1080, 3)

    print('[3] 相位与隔行')
    c.eq('垂直 1:1 相位值', hex(PHASE_V_1_1), hex(0x02000000))
    c.eq('水平 1:1 相位值', hex(PHASE_H_1_1), hex(0x01000000))
    c.true('U-Boot 残留 bit23（隔行）为 1', bool(HW_VSC_CTRL0 & (1 << 23)))
    c.true('修正值 bit23 已清', not (VSC_CTRL0_FIXED & (1 << 23)))
    c.true('修正值保留 bit24（缩放使能）', bool(VSC_CTRL0_FIXED & (1 << 24)))

    print('[4] 与 osdfix.sh 的一致性（曾用错 0x1d00 段）')
    of_path = os.path.join(ROOT, 'out/deb13-new/osdfix.sh')
    if os.path.exists(of_path):
        of = _read('out/deb13-new/osdfix.sh')
        for name, reg, val in APPLIED:
            token = '0x%04x:0x%08x' % (reg * 4, val)
            c.true('osdfix 含 %s (%s)' % (name, token), token in of, 'missing')
    else:
        print('  SKIP osdfix.sh: out/deb13-new/osdfix.sh 不存在（干净检出）')

    print('[5] 源码位宽（回归）')
    refs = [
        ('out/rashim/blit_core.h', 'blit_core.h 为 3 字节像素', ('#define CB 3',), True),
        ('out/rashim/blit_core.h', 'blit_core.h 无显存回读', ('memcpy(dst, dst - stride',), False),
        ('out/shim/shim.c', 'shim.c 为 24bpp 画布', ('CANVAS_BYTES   3', 'CANVAS_BYTES 3'), True),
        ('out/deb13-new/autostart.sh', 'autostart 调用 osdfix.sh', ('osdfix.sh',), True),
        ('out/deb13-new/autostart.sh', 'autostart 不再内联写 0x86F', ('0x0000086f',), False),
    ]
    for rel, name, tokens, want in refs:
        if not os.path.exists(os.path.join(ROOT, rel)):
            print('  SKIP %s: %s 不存在（干净检出）' % (name, rel))
            continue
        content = _read(rel)
        found = any(token in content for token in tokens)
        c.true(name, found == want)

    print('\n==== %d PASS / %d FAIL ====' % (c.n - c.fail, c.fail))
    return 1 if c.fail else 0


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        sys.exit(selftest())
    print(__doc__)
