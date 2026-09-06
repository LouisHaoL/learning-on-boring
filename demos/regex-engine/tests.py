# -*- coding: utf-8 -*-
"""断言脚本:双后端一致性 + 与 Python re 交叉验证 + 捕获组 + 性能冒烟。

运行:  python tests.py
全部通过输出 ALL TESTS PASSED,否则以非零码退出。
"""

import os
import re
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from parser import ParseError, parse
from backtrack import BacktrackRegex
from thompson import ThompsonRegex

failures = []
passed = 0


def check(name, cond, detail=''):
    global passed
    if cond:
        passed += 1
    else:
        failures.append(f'{name}: {detail}')
        print(f'FAIL {name}: {detail}')


# ---------------------------------------------------------------------------
# 1. 匹配结果一致性(双后端 + Python re),覆盖全部支持语法
#    (pattern, text)
# ---------------------------------------------------------------------------
CASES = [
    # 字面量
    ('abc', 'abc'), ('abc', 'ab'), ('abc', 'xxabcxx'), ('abc', 'ABC'),
    # 点号
    (r'a.c', 'abc'), (r'a.c', 'ac'), (r'a.c', 'axc'), (r'a.c', 'a\nc'),
    (r'.', ''), (r'...', 'ab'),
    # 星号 / 加号 / 问号
    ('a*', ''), ('a*', 'aaa'), ('a*', 'bbb'), ('a+', ''), ('a+', 'aa'),
    ('a+', 'b'), ('a?', ''), ('a?', 'a'), ('a?', 'aa'), ('ba?', 'b'),
    ('ba?', 'ba'), ('ba?', 'baa'),
    # 计数量词
    ('a{3}', 'aa'), ('a{3}', 'aaa'), ('a{3}', 'aaaa'), ('a{2,}', 'a'),
    ('a{2,}', 'aaaa'), ('a{2,4}', 'a'), ('a{2,4}', 'aaaaa'),
    ('a{0,2}', ''), ('a{2,2}', 'aa'), ('(ab){2}', 'ababab'),
    ('a{,3}', 'aaa'), ('a{,3}', 'aaaa'), ('a{,2}b', 'b'), ('a{,2}b', 'aaab'),
    ('(ab){1,2}', 'ababab'), ('a{2}b{1,3}', 'aabbb'), ('a{1,}', ''),
    # 字符类
    ('[abc]', 'd'), ('[abc]', 'b'), ('[a-z]+', 'ABC'), ('[a-z]+', 'abc'),
    ('[a-zA-Z]+', 'aZ9'), ('[0-9]+', 'x42x'), ('[^abc]', 'a'),
    ('[^abc]', 'd'), ('[^0-9]', '5'), ('[a-c-]', '-'), ('[-a]', '-'),
    (r'[\d]+', '12a'), (r'[\da-f]+', 'ff0g'), (r'[^\d]+', '12'),
    (r'[^\d]+', 'ab'), ('[.]*', '...'), ('[^^]', '^'), ('[a^]', '^'),
    (r'[a\-z]', '-'), ('[]a]', 'a'),
    # 锚点
    ('^abc', 'abcd'), ('^abc', 'xabc'), ('abc$', 'xabc'), ('abc$', 'abcx'),
    ('^abc$', 'abc'), ('^$', ''), ('^$', 'a'), ('^a+b$', 'aaab'),
    ('a^b', 'ab'), ('a$b', 'ab'), ('^', 'abc'), ('$', 'abc'),
    # 分组与选择
    ('(ab)+c', 'ababc'), ('(a|b)*c', 'abbac'), ('cat|dog', 'hotdog'),
    ('(cat|dog)s?', 'cats'), ('(?:ab)+', 'abab'), ('(a(b(c)))', 'abc'),
    ('a||b', ''), ('(|a)', 'a'), ('x(a|y)b', 'xyb'), ('(a)*', 'aaa'),
    ('(a|b)|(c|d)', 'c'), ('gr(e|a)y', 'grey'), ('()', 'x'),
    ('(a+)(b+)', 'aabbb'), ('(a)(b)?', 'a'), ('(x)|(y)', 'y'),
    ('(?:a)(b)', 'ab'),
    # 转义
    (r'\d+', 'abc123def'), (r'\d+', 'abc'), (r'\D+', '123'),
    (r'\w+', 'hello_world 42'), (r'\W', 'ab-cd'), (r'\s\s', 'a  b'),
    (r'\S+', '   hi  '), (r'\.', 'a.b'), (r'a\.c', 'abc'),
    (r'\( \)', 'call ( ) now'), (r'a\\b', 'a\\b'), (r'\n', 'a\nb'),
    (r'a\tb', 'a\tb'), (r'\D\d\w', 'a1x'),
    # 组合 & 灾难模式(小规模)
    ('(a+)+b', 'aaab'), ('(a+)+b', 'aaac'), ('(a|a)*b', 'aaaaab'),
    ('(a|a)*b', 'aaaaac'), ('(a*)*b', 'aab'), ('(a?)*b', 'ab'),
    ('(a*)*$', ''), ('^(a|aa)+$', 'aaaa'),
    # 其他
    ('', 'abc'), ('.*', 'anything'), ('a*b*c*', 'abcabc'),
    ('[a-z]*[0-9]', 'abc9'), ('a|', 'a'), ('|a', 'b'),
]

# ---------------------------------------------------------------------------
# 2. 硬编码期望值(防止三方同时错)—— (pattern, text, expected)
# ---------------------------------------------------------------------------
HARDCODED = [
    ('abc', 'abc', True), ('a+b', 'b', False), ('a{3}', 'aa', False),
    ('^ab$', 'ab', True), ('[^a]', 'a', False), ('(a|b)+c', 'xxc', False),
    (r'\d{4}', '2026', True), ('a.c', 'a\nc', False), ('a*', 'zzz', True),
    ('(a+)+b', 'a' * 10 + 'X', False),
]


def main():
    # --- 一致性 + re 交叉验证 ---
    for i, (pat, text) in enumerate(CASES):
        bt = BacktrackRegex(pat).search(text) is not None
        tp = ThompsonRegex(pat).search(text)
        py = re.search(pat, text) is not None
        check(f'case#{i} {pat!r} ~ {text!r}', bt == tp == py,
              f'backtrack={bt} thompson={tp} re={py}')

    for i, (pat, text, exp) in enumerate(HARDCODED):
        bt = BacktrackRegex(pat).search(text) is not None
        tp = ThompsonRegex(pat).search(text)
        py = re.search(pat, text) is not None
        check(f'hard#{i} {pat!r}', bt == tp == py == exp,
              f'backtrack={bt} thompson={tp} re={py} expected={exp}')

    # --- 捕获组语义 vs Python re(仅回溯后端提供) ---
    CAPTURE_CASES = [
        (r'(a+)(b+)', 'xxaabbbzz'),
        (r'(a)(b)?', 'a'),
        (r'(a(b(c)))', 'zzabc'),
        (r'(x)|(y)', 'yy'),
        (r'(?:a)(b+)', 'aabbb'),
        (r'(\d+)-(\d+)', 'id: 12-345;'),
        (r'([a-z]+)@([a-z]+)\.com', 'mail: bob@example.com;'),
        (r'(a*)(b)', 'aab'),
    ]
    for i, (pat, text) in enumerate(CAPTURE_CASES):
        m1 = BacktrackRegex(pat).search(text)
        m2 = re.search(pat, text)
        check(f'cap#{i} {pat!r} matched', (m1 is not None) == (m2 is not None))
        if m1 and m2:
            check(f'cap#{i} {pat!r} span',
                  (m1.start, m1.end) == (m2.start(), m2.end()),
                  f'{(m1.start, m1.end)} vs {(m2.start(), m2.end())}')
            check(f'cap#{i} {pat!r} groups', m1.groups == m2.groups(),
                  f'{m1.groups} vs {m2.groups()}')

    # --- 语法错误应抛 ParseError ---
    BAD = ['*a', '+a', '?a', 'a**', '[a', '(a', 'a)', '(?P<x>a)',
           r'\q', r'\b', 'a{2,1}', '[z-a]', 'a{1,2}{3}', '^*']
    for pat in BAD:
        try:
            parse(pat)
            check(f'bad {pat!r}', False, '未抛出 ParseError')
        except ParseError:
            check(f'bad {pat!r} raises', True)

    # --- 性能冒烟:回溯在 n=18 灾难用例会明显变慢,Thompson 恒快 ---
    t0 = time.perf_counter()
    ThompsonRegex('(a+)+b').search('a' * 5000 + 'X')
    tp_ms = (time.perf_counter() - t0) * 1000
    check('thompson 5000 chars linear', tp_ms < 2000, f'{tp_ms:.1f} ms')

    t0 = time.perf_counter()
    BacktrackRegex('(a+)+b').search('a' * 18 + 'X')
    bt18_ms = (time.perf_counter() - t0) * 1000
    t0 = time.perf_counter()
    BacktrackRegex('(a+)+b').search('a' * 20 + 'X')
    bt20_ms = (time.perf_counter() - t0) * 1000
    check('backtrack exponential growth', bt20_ms > bt18_ms * 2,
          f'n=18 {bt18_ms:.1f} ms, n=20 {bt20_ms:.1f} ms (应约 4 倍)')

    # --- CLI 自检 ---
    here = os.path.dirname(os.path.abspath(__file__))
    env = dict(os.environ, PYTHONIOENCODING='utf-8')
    r = subprocess.run(
        [sys.executable, os.path.join(here, 'cli.py'),
         r'(a|b)+c', 'ababc', '--backend', 'both'],
        capture_output=True, text=True, encoding='utf-8', env=env)
    check('cli exit 0', r.returncode == 0, r.stderr)
    check('cli output', '匹配' in r.stdout and 'backtrack' in r.stdout
          and 'thompson' in r.stdout, r.stdout)

    # --- 汇总 ---
    total = passed + len(failures)
    print(f'\n{passed}/{total} checks passed')
    if failures:
        print('FAILED:')
        for f in failures:
            print(' -', f)
        sys.exit(1)
    print('ALL TESTS PASSED')


if __name__ == '__main__':
    main()
