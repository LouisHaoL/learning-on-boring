# -*- coding: utf-8 -*-
"""命令行入口。

用法:
    python cli.py '<pattern>' '<text>' [--backend backtrack|thompson|both]
"""

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Windows 控制台默认 GBK,强制 UTF-8 避免中文输出乱码
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")

from backtrack import BacktrackRegex, StepLimitExceeded
from thompson import ThompsonRegex


def main(argv=None):
    ap = argparse.ArgumentParser(description='教学用正则引擎(双后端)')
    ap.add_argument('pattern', help='正则表达式')
    ap.add_argument('text', help='被搜索的文本')
    ap.add_argument('--backend', choices=['backtrack', 'thompson', 'both'],
                    default='both', help='选择后端(默认 both)')
    ap.add_argument('--max-steps', type=int, default=5_000_000,
                    help='回溯步数上限,防止 ReDoS 用例跑不完(默认 5,000,000)')
    args = ap.parse_args(argv)

    print(f'pattern : {args.pattern!r}')
    print(f'text    : {args.text!r}  (len={len(args.text)})')

    if args.backend in ('backtrack', 'both'):
        t0 = time.perf_counter()
        try:
            m = BacktrackRegex(args.pattern).search_with_limit(
                args.text, args.max_steps)
            dt = (time.perf_counter() - t0) * 1000
            if m:
                print(f'backtrack: 匹配  [{m.start}, {m.end})  '
                      f'groups={m.groups}  ({dt:.3f} ms)')
            else:
                print(f'backtrack: 不匹配  ({dt:.3f} ms)')
        except StepLimitExceeded as e:
            print(f'backtrack: {e}')

    if args.backend in ('thompson', 'both'):
        t0 = time.perf_counter()
        nfa = ThompsonRegex(args.pattern)
        build_ms = (time.perf_counter() - t0) * 1000
        t0 = time.perf_counter()
        ok = nfa.search(args.text)
        dt = (time.perf_counter() - t0) * 1000
        print(f'thompson : {"匹配" if ok else "不匹配"}  '
              f'(NFA {nfa.nstates} 状态, 构建 {build_ms:.3f} ms, '
              f'搜索 {dt:.3f} ms)')

    return 0


if __name__ == '__main__':
    sys.exit(main())
