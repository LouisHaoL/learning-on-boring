# -*- coding: utf-8 -*-
"""性能实验:回溯后端 vs Thompson NFA 后端。

实验 1:ReDoS 灾难案例 (a+)+b 对 'a'*n + 'X'(失败匹配,回溯指数爆炸)
实验 2:同一模式对 'a'*n + 'b'(成功匹配,贪婪一次走通,双方都快)
实验 3:Thompson 的可扩展性(n 到十万级仍近似线性)

运行:  python bench.py
输出为 Markdown 表格,可直接粘进 README。
"""

import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backtrack import BacktrackRegex, StepLimitExceeded
from thompson import ThompsonRegex

PATTERN = '(a+)+b'
STEP_LIMIT = 20_000_000  # 回溯步数上限:超过即判“爆炸剪断”


def timed(fn):
    t0 = time.perf_counter()
    fn()
    return time.perf_counter() - t0


def fmt_s(sec):
    if sec < 1e-3:
        return f'{sec * 1e6:8.1f} us'
    if sec < 1:
        return f'{sec * 1e3:8.2f} ms'
    return f'{sec:8.3f} s '


def main():
    bt = BacktrackRegex(PATTERN)
    tp = ThompsonRegex(PATTERN)
    print(f'模式: {PATTERN}   回溯步数上限: {STEP_LIMIT:,}')
    print(f'Python {sys.version.split()[0]}, '
          f'文本 = "a"*n + "X"(除非注明)\n')

    # ---- 实验 1:失败匹配,回溯爆炸 ----
    print('## 实验 1:ReDoS 灾难案例(匹配失败,触发指数回溯)\n')
    print('| n("a"个数) | 回溯后端 | Thompson NFA |')
    print('|---:|---|---|')
    exp1 = []
    for n in (4, 8, 12, 16, 20, 24, 28, 32):
        text = 'a' * n + 'X'
        try:
            t_bt = timed(lambda: bt.search_with_limit(text, STEP_LIMIT))
            bt_cell = fmt_s(t_bt)
            exp1.append((n, t_bt))
        except StepLimitExceeded:
            bt_cell = f'> {STEP_LIMIT:,} 步(剪断)'
            exp1.append((n, None))
        t_tp = timed(lambda: tp.search(text))
        print(f'| {n} | {bt_cell} | {fmt_s(t_tp)} |')

    # ---- 实验 2:成功匹配(贪心一次走通) ----
    print('\n## 实验 2:匹配成功(贪婪一次走通,回溯也不爆炸)\n')
    print('| n("a"个数,文本以 b 结尾) | 回溯后端 | Thompson NFA |')
    print('|---:|---|---|')
    for n in (100, 1_000, 5_000):
        text = 'a' * n + 'b'
        assert bt.search(text) and tp.search(text)
        t_bt = timed(lambda: bt.search_with_limit(text, STEP_LIMIT))
        t_tp = timed(lambda: tp.search(text))
        print(f'| {n} | {fmt_s(t_bt)} | {fmt_s(t_tp)} |')

    # ---- 实验 3:Thompson 大规模扩展性 ----
    print('\n## 实验 3:Thompson 线性扩展性(失败匹配,n 到十万)\n')
    print('| n | Thompson 耗时 | 每字符耗时 |')
    print('|---:|---|---|')
    per_char = []
    for n in (1_000, 10_000, 50_000, 100_000):
        text = 'a' * n + 'X'
        t_tp = timed(lambda: tp.search(text))
        per_char.append(t_tp / (n + 1))
        print(f'| {n} | {fmt_s(t_tp)} | {t_tp / (n + 1) * 1e6:.2f} us |')

    # ---- ASCII 曲线:实验 1 回溯耗时(对数刻度) ----
    measured = [(n, t) for n, t in exp1 if t is not None]
    if len(measured) >= 2:
        print('\n### 回溯后端耗时曲线(实验 1,对数刻度,1 格 ≈ x2)\n')
        t_min = measured[0][1]
        for n, t in measured:
            cells = max(1, round((math.log2(max(t, 1e-7)) -
                                  math.log2(max(t_min, 1e-7))) / 1.0))
            print(f'n={n:3d} |{"#" * cells} {fmt_s(t)}')
        for n, t in exp1:
            if t is None:
                print(f'n={n:3d} | (超出步数上限,已剪断 —— 真实耗时为指数级)')

    cut = next((n for n, t in exp1 if t is None), None)
    print(f'\n结论:回溯后端 n 每增加 4 耗时约 x16(指数 O(2^n));'
          f'n={cut} 时超过 {STEP_LIMIT:,} 步上限。')
    print('Thompson 对同样的模式、上万字符的输入仍然微秒级完成,'
          '每字符耗时稳定在同一个数量级(线性)。')


if __name__ == '__main__':
    main()
