# -*- coding: utf-8 -*-
"""回溯后端:AST 直接编译为嵌套闭包,深度优先尝试所有路径。

这是 PCRE / Python re / Java 等传统引擎的工作方式:
  - 优点:匹配过程是一条具体的路径,可以顺手记录捕获组、支持反向引用等;
  - 缺点:同一位置可能被指数次重新尝试(ReDoS),最坏 O(2^n)。

实现要点(continuation-passing):
  每个节点编译成  fn(text, pos, caps, counter, cont) -> bool,
  cont 是“后续匹配”的闭包;失败时返回 False,由上层换一条路重试。
  counter 是可选的步数计数器(list),用于给灾难回溯实验“剪断”。
"""

import sys

from parser import (RegexError, Empty, Char, Any, Class, Start, End,
                    Cat, Alt, Rep, Group, parse)


class StepLimitExceeded(RegexError):
    """搜索步数超过上限(防止实验跑不完)。"""


sys.setrecursionlimit(max(sys.getrecursionlimit(), 20000))

_NO_COUNT = None  # counter 传 None 表示不计数


def _empty_fn(text, pos, caps, counter, cont):
    return cont(pos)


def _seq(f, g):
    """组合两段:f 匹配成功后接着跑 g。"""
    def fn(text, pos, caps, counter, cont):
        return f(text, pos, caps, counter,
                 lambda p: g(text, p, caps, counter, cont))
    return fn


def _make_star(b):
    """贪婪星号:优先多迭代,整体失败再回退到“零次”。

    k 里的 p == pos 守卫防止空迭代死循环(如 (a*)* 对任意输入)。
    """
    def fn(text, pos, caps, counter, cont):
        def k(p):
            if p == pos:
                return False  # 本次迭代没消耗字符,停止继续迭代
            return fn(text, p, caps, counter, cont)
        return b(text, pos, caps, counter, k) or cont(pos)
    return fn


def _make_bounded(b, n):
    """最多再迭代 n 次的贪婪循环(用于 {m,n} 的可变部分)。"""
    if n == 0:
        return _empty_fn
    inner = _make_bounded(b, n - 1)

    def fn(text, pos, caps, counter, cont):
        def k(p):
            if p == pos:
                return False
            return inner(text, p, caps, counter, cont)
        return b(text, pos, caps, counter, k) or cont(pos)
    return fn


def _build(node):
    t = type(node)

    if t is Char or t is Any or t is Class:
        matcher = node.match

        def fn(text, pos, caps, counter, cont):
            if counter is not None:
                counter[0] += 1
                if counter[0] > counter[1]:
                    raise StepLimitExceeded(
                        f'回溯步数超过 {counter[1]:,},已剪断')
            return pos < len(text) and matcher(text[pos]) and cont(pos + 1)
        return fn

    if t is Empty:
        return _empty_fn

    if t is Start:
        def fn(text, pos, caps, counter, cont):
            return pos == 0 and cont(pos)
        return fn

    if t is End:
        def fn(text, pos, caps, counter, cont):
            return pos == len(text) and cont(pos)
        return fn

    if t is Cat:
        fns = [_build(p) for p in node.parts]
        if len(fns) == 1:
            return fns[0]
        combined = fns[-1]
        for f in reversed(fns[:-1]):
            combined = _seq(f, combined)
        return combined

    if t is Alt:
        fns = [_build(p) for p in node.parts]

        def fn(text, pos, caps, counter, cont):
            for f in fns:
                if f(text, pos, caps, counter, cont):
                    return True
            return False
        return fn

    if t is Rep:
        b = _build(node.child)
        lo, hi = node.min, node.max
        head = _empty_fn
        for _ in range(lo):
            head = _seq(head, b)
        if hi is None:
            tail = _make_star(b)
        elif hi == lo:
            tail = _empty_fn
        else:
            tail = _make_bounded(b, hi - lo)
        if head is _empty_fn:
            return tail
        return _seq(head, tail)

    if t is Group:
        b = _build(node.child)
        s, e = 2 * node.index, 2 * node.index + 1

        def fn(text, pos, caps, counter, cont):
            old_s, old_e = caps[s], caps[e]
            caps[s] = pos  # 进组:记录起点
            def k(p):
                old = caps[e]
                caps[e] = p  # 出组:记录终点
                if cont(p):
                    return True
                caps[e] = old
                return False
            ok = b(text, pos, caps, counter, k)
            if not ok:
                caps[s], caps[e] = old_s, old_e  # 整组失败,回滚捕获
            return ok
        return fn

    raise TypeError(f'未知 AST 节点: {t}')


class Match:
    """匹配结果(仅回溯后端携带捕获组)。"""
    __slots__ = ('start', 'end', 'groups')

    def __init__(self, start, end, groups):
        self.start = start
        self.end = end
        self.groups = groups  # tuple,未参与匹配的组为 None

    def __repr__(self):
        return f'Match(span=({self.start}, {self.end}), groups={self.groups!r})'


class BacktrackRegex:
    """编译一次,可对多个文本搜索。"""

    def __init__(self, pattern):
        self.pattern = pattern
        ast, self.ngroups = parse(pattern)
        self._fn = _build(ast)

    def search(self, text):
        """从左到右找第一个匹配,返回 Match 或 None。"""
        return self._run(text, None)

    def search_with_limit(self, text, limit):
        """同 search,但字符尝试次数超过 limit 时抛 StepLimitExceeded。"""
        return self._run(text, limit)

    def _run(self, text, limit):
        fn = self._fn
        n = len(text)
        # counter[0]=已消耗步数; counter[1]=上限(None 表示不设限)
        counter = [0, limit] if limit is not None else _NO_COUNT
        for start in range(n + 1):
            caps = [None] * (2 * (self.ngroups + 1))
            end_holder = [None]

            def cont(p, _h=end_holder):
                _h[0] = p
                return True

            if fn(text, start, caps, counter, cont):
                groups = tuple(
                    text[caps[2 * i]:caps[2 * i + 1]]
                    if caps[2 * i] is not None and caps[2 * i + 1] is not None
                    else None
                    for i in range(1, self.ngroups + 1))
                return Match(start, end_holder[0], groups)
        return None
