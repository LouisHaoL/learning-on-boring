# -*- coding: utf-8 -*-
"""Thompson NFA 后端:AST -> NFA 片段拼装 -> 多状态并行模拟。

理论保证(Thompson 1968 / Russ Cox "Regular Expression Matching Can Be
Simple And Fast"):同时跟踪 NFA 的**状态集合**而不是单条路径,
每个输入字符只做一遍状态转移,时间 O(文本长度 x 状态数),与路径组合数无关。

实现要点:
  - 片段(fragment)= (start 状态, 悬空指针列表);悬空指针最后 patch 到
    下一个片段的入口,这是 Thompson 构造法的经典写法。
  - 锚点 ^ $ 建成“条件 epsilon 边”(只在 pos==0 / pos==len 时可通过),
    于是模拟仍然只需逐字符推进。
  - 不捕获组:分组节点对 NFA 完全透明,这是该后端“线性但有牺牲”的原因之一。
"""

from parser import (Empty, Char, Any, Class, Start, End, Cat, Alt, Rep,
                    Group, parse)


class State:
    """NFA 状态。

    test  : 字符谓词节点(Char/Any/Class,提供 .match(ch));None 表示纯 epsilon 节点
    out   : 字符转移的唯一出口
    eps   : epsilon 转移列表 [(cond, target)];cond 为 None / 'bol' / 'eol',
            target 为 None 表示悬空待 patch
    """
    __slots__ = ('test', 'out', 'eps')

    def __init__(self, test=None):
        self.test = test
        self.out = None
        self.eps = []


def _patch(dangling, target):
    """把片段的所有悬空出口接到 target 状态。"""
    for d in dangling:
        kind, state, idx = d
        if kind == 'out':
            state.out = target
        else:  # ('eps', state, i)
            cond = state.eps[idx][0]
            state.eps[idx] = (cond, target)


def _build_nfa(node):
    """把 AST 节点编译成片段 (start, dangling)。"""
    t = type(node)

    # ---- 字符类节点:单字符转移 ----
    if t in (Char, Any, Class):
        s = State(node)
        return s, [('out', s, None)]

    if t is Empty:
        s = State()
        s.eps = [(None, None)]
        return s, [('eps', s, 0)]

    if t is Start:
        s = State()
        s.eps = [('bol', None)]
        return s, [('eps', s, 0)]

    if t is End:
        s = State()
        s.eps = [('eol', None)]
        return s, [('eps', s, 0)]

    if t is Cat:
        parts = [_build_nfa(p) for p in node.parts]
        start, dangling = parts[0]
        for f_start, f_dangling in parts[1:]:
            _patch(dangling, f_start)
            dangling = f_dangling
        return start, dangling

    if t is Alt:
        s = State()  # split 状态:两条 epsilon 出边
        frags = [_build_nfa(p) for p in node.parts]
        s.eps = [(None, f[0]) for f in frags]
        dangling = [d for f in frags for d in f[1]]
        return s, dangling

    if t is Rep:
        lo, hi = node.min, node.max
        # 必需部分:lo 份拷贝串联
        head_start, dangling = None, None
        for _ in range(lo):
            f = _build_nfa(node.child)
            if head_start is None:
                head_start, dangling = f
            else:
                _patch(dangling, f[0])
                dangling = f[1]
        # 可变部分
        if hi is None:                      # 星号:分裂回边
            f = _build_nfa(node.child)
            s = State()
            s.eps = [(None, f[0]), (None, None)]
            _patch(f[1], s)
            if head_start is None:
                return s, [('eps', s, 1)]
            _patch(dangling, s)
            return head_start, [('eps', s, 1)]
        if hi == lo:                        # 精确次数
            if head_start is None:          # {0}
                s = State()
                s.eps = [(None, None)]
                return s, [('eps', s, 0)]
            return head_start, dangling
        # {lo,hi}:后面再串 (hi-lo) 个“可选”拷贝
        opt_dangling = []
        for _ in range(hi - lo):
            f = _build_nfa(node.child)
            s = State()
            s.eps = [(None, f[0]), (None, None)]
            if head_start is None:
                head_start, dangling = s, []
            else:
                _patch(dangling, s)
            opt_dangling.extend(f[1])
            opt_dangling.append(('eps', s, 1))
            dangling = opt_dangling
            opt_dangling = []
        return head_start, dangling

    if t is Group:
        return _build_nfa(node.child)  # 分组对 NFA 透明:没有捕获

    raise TypeError(f'未知 AST 节点: {t}')


def _closure(states, pos, n):
    """epsilon 闭包;锚点边按当前位置 pos 决定能否通过。"""
    seen = set(states)
    stack = list(states)
    while stack:
        s = stack.pop()
        for cond, tgt in s.eps:
            if tgt is None:
                continue
            if cond == 'bol' and pos != 0:
                continue
            if cond == 'eol' and pos != n:
                continue
            if tgt not in seen:
                seen.add(tgt)
                stack.append(tgt)
    return seen


class ThompsonRegex:
    """编译一次,可对多个文本搜索。只回答“是否匹配”,不提供捕获组。"""

    def __init__(self, pattern):
        self.pattern = pattern
        ast, self.ngroups = parse(pattern)
        start, dangling = _build_nfa(ast)
        self.accept = State()
        _patch(dangling, self.accept)
        self.start = start
        self.nstates = _count_states(start, self.accept)

    def search(self, text):
        """未锚定搜索:每个位置(含串尾)都允许“重新从起始状态出发”。"""
        start, accept = self.start, self.accept
        n = len(text)
        current = set()
        for i in range(n + 1):
            current |= _closure({start}, i, n)  # 新匹配可从位置 i 开始
            if accept in current:
                return True
            if i == n:
                break
            ch = text[i]
            nxt = {s.out for s in current
                   if s.test is not None and s.test.match(ch)}
            current = _closure(nxt, i + 1, n)
        return False


def _count_states(start, accept):
    seen = set()
    stack = [start, accept]
    while stack:
        s = stack.pop()
        if s in seen:
            continue
        seen.add(s)
        if s.out is not None:
            stack.append(s.out)
        for _, tgt in s.eps:
            if tgt is not None:
                stack.append(tgt)
    return len(seen)
