# -*- coding: utf-8 -*-
"""正则表达式解析器:pattern 字符串 -> AST(递归下降)。

两种后端(backtrack.py / thompson.py)共用这里的 AST。

语法(暂不支持:懒惰量词 a+?、反向引用 \\1、词边界 \\b、内联标志 (?i)):
    .  *  +  ?  {m,n} {m,} {m}      基础量词(仅贪婪)
    [abc]  [a-z]  [^abc]            字符类(支持区间/取反/类内转义)
    ^  $                            锚点(无多行模式:^ 仅串首,$ 仅串尾)
    (...)  (?:...)                  捕获 / 非捕获分组
    a|b                             选择
    \\d \\w \\s \\D \\W \\S          类转义;标点转义 \\.;控制符 \\n \\t \\r \\f \\v
"""

MEANINGLESS = object()  # 占位,防止误用


class RegexError(Exception):
    """正则引擎统一异常基类。"""


class ParseError(RegexError):
    """语法错误。"""


# ---------------------------------------------------------------------------
# AST 节点定义
# ---------------------------------------------------------------------------

class Node:
    __slots__ = ()


class Empty(Node):
    """空表达式,恒匹配空串。"""
    __slots__ = ()

    def match(self, ch):  # pragma: no cover - 仅供接口统一
        return False


class Char(Node):
    """单个字面字符。"""
    __slots__ = ('ch',)

    def __init__(self, ch):
        self.ch = ch

    def match(self, ch):
        return ch == self.ch


class Any(Node):
    """`.` :除换行符外的任意字符(无 DOTALL 语义,与 Python re 默认一致)。"""
    __slots__ = ()

    def match(self, ch):
        return ch != '\n'


class Class(Node):
    """字符类 [..] / [^..]。items 为 (lo, hi) 闭区间列表。"""
    __slots__ = ('items', 'negated')

    def __init__(self, items, negated):
        self.items = items
        self.negated = negated

    def match(self, ch):
        hit = any(lo <= ch <= hi for lo, hi in self.items)
        return hit != self.negated


class Start(Node):
    """`^` :文本开头。"""
    __slots__ = ()


class End(Node):
    """`$` :文本结尾(不含 Python re 的“末尾换行前”分支)。"""
    __slots__ = ()


class Cat(Node):
    """连接:e1 e2 e3 ..."""
    __slots__ = ('parts',)

    def __init__(self, parts):
        self.parts = parts


class Alt(Node):
    """选择:e1 | e2 | ..."""
    __slots__ = ('parts',)

    def __init__(self, parts):
        self.parts = parts


class Rep(Node):
    """重复:child{min, max};max 为 None 表示无上限。"""
    __slots__ = ('child', 'min', 'max')

    def __init__(self, child, lo, hi):
        self.child = child
        self.min = lo
        self.max = hi


class Group(Node):
    """捕获分组,index 为 1 起始的组号。"""
    __slots__ = ('index', 'child')

    def __init__(self, index, child):
        self.index = index
        self.child = child


# ---------------------------------------------------------------------------
# 转义
# ---------------------------------------------------------------------------

# \d \w \s 对应的区间(仅 ASCII 语义,与 Python re 对纯 ASCII 文本的行为一致)
_ESC_CLASSES = {
    'd': [('0', '9')],
    'w': [('0', '9'), ('A', 'Z'), ('_', '_'), ('a', 'z')],
    's': [(' ', ' '), ('\x09', '\x0d')],  # 空格 + \t\n\v\f\r
}
_CTRL_ESCAPES = {'n': '\n', 't': '\t', 'r': '\r', 'f': '\f', 'v': '\v', '0': '\0'}


def _escape_node(c):
    """解析类外转义(反斜杠后的字符),返回 AST 节点。"""
    low = c.lower()
    if low in _ESC_CLASSES:
        return Class(_ESC_CLASSES[low], c.isupper())
    if c in _CTRL_ESCAPES:
        return Char(_CTRL_ESCAPES[c])
    if c == 'b':
        raise ParseError(r'不支持词边界 \b(Thompson NFA 无法线性支持它)')
    if c.isalnum():
        raise ParseError(rf'不支持的转义 \{c}')
    return Char(c)  # 标点转义: \. \\ \( 等


def _escape_in_class(c):
    """解析类内转义,返回 (lo, hi) 区间列表(单字符区间 hi==lo)。"""
    low = c.lower()
    if low in _ESC_CLASSES:
        return _ESC_CLASSES[c]  # 类转义展开为多区间
    if c == 'b':
        return [('\x08', '\x08')]  # 类内 \b = 退格符
    if c in _CTRL_ESCAPES:
        ch = _CTRL_ESCAPES[c]
        return [(ch, ch)]
    if c.isalnum():
        raise ParseError(rf'字符类内不支持的转义 \{c}')
    return [(c, c)]


# ---------------------------------------------------------------------------
# 递归下降解析器
#
# 文法:
#   alt    := concat ('|' concat)*
#   concat := repeat*
#   repeat := atom ( '*' | '+' | '?' | '{m,n}' )*
#   atom   := char | '.' | '^' | '$' | escape | class | '(' alt ')'
# ---------------------------------------------------------------------------

class _Parser:
    def __init__(self, pattern):
        self.pat = pattern
        self.i = 0
        self.ngroups = 0

    # ---- 基础工具 ----
    def peek(self, ahead=0):
        j = self.i + ahead
        return self.pat[j] if j < len(self.pat) else None

    def take(self):
        c = self.peek()
        if c is None:
            raise ParseError('正则表达式意外结束')
        self.i += 1
        return c

    def error(self, msg):
        raise ParseError(f'位置 {self.i}: {msg}')

    # ---- 文法规则 ----
    def parse(self):
        node = self.alt()
        if self.i < len(self.pat):
            self.error(f"意外的字符 '{self.peek()}'(多余右括号?)")
        return node

    def alt(self):
        parts = [self.concat()]
        while self.peek() == '|':
            self.i += 1
            parts.append(self.concat())
        return parts[0] if len(parts) == 1 else Alt(parts)

    def concat(self):
        parts = []
        while self.peek() is not None and self.peek() not in '|)':
            parts.append(self.repeat())
        if not parts:
            return Empty()
        return parts[0] if len(parts) == 1 else Cat(parts)

    def repeat(self):
        atom = self.atom()
        while True:
            c = self.peek()
            if c == '*':
                lo, hi = 0, None
                self.i += 1
            elif c == '+':
                lo, hi = 1, None
                self.i += 1
            elif c == '?':
                lo, hi = 0, 1
                self.i += 1
            elif c == '{':
                counted = self._try_counted()
                if counted is None:
                    break
                lo, hi = counted  # _try_counted 已消费整个 {...}
                if hi is not None and hi < lo:
                    self.error(f'量词重复次数反序: {{{lo},{hi}}}')
            else:
                break
            if isinstance(atom, (Start, End, Empty)):
                self.error('量词不能作用于锚点或空表达式')
            if isinstance(atom, Rep):
                self.error('不支持量词叠加(如 a**),请用括号明确分组')
            atom = Rep(atom, lo, hi)
        return atom

    def _try_counted(self):
        """解析 {m} {m,} {m,n} {,n};失败返回 None(不消费字符)。"""
        save = self.i
        self.i += 1  # 跳过 '{'
        lo = self._digits()
        c = self.peek()
        if c == '}':
            if lo is None:  # '{}' 不是量词
                self.i = save
                return None
            self.i += 1
            return (int(lo), int(lo))
        if c == ',':
            self.i += 1
            hi = self._digits()
            if self.peek() == '}' and (lo is not None or hi is not None):
                self.i += 1
                return (int(lo) if lo is not None else 0,
                        int(hi) if hi is not None else None)
        self.i = save
        return None

    def _digits(self):
        out = []
        while (self.peek() or '').isdigit():
            out.append(self.take())
        return ''.join(out) if out else None

    def atom(self):
        c = self.peek()
        if c is None:
            self.error('缺少表达式')
        if c == '(':
            return self._group()
        if c == '[':
            return self._charclass()
        if c == '.':
            self.i += 1
            return Any()
        if c == '^':
            self.i += 1
            return Start()
        if c == '$':
            self.i += 1
            return End()
        if c == '\\':
            self.i += 1
            return _escape_node(self.take())
        if c in '*+?':
            self.error(f"量词 '{c}' 前缺少可重复的元素")
        if c == '{':
            # 单独出现的 '{':严格要求是合法量词,否则报错(比 Python 严格)
            counted = self._try_counted()
            if counted is None:
                self.error("孤立的 '{'")
            self.error('量词前缺少可重复的元素')
        self.i += 1
        return Char(c)

    def _group(self):
        self.i += 1  # '('
        capture = True
        if self.peek() == '?':
            self.i += 1
            if self.peek() == ':':
                self.i += 1
                capture = False
            else:
                self.error('仅支持 (?:...) 非捕获分组(不支持 (?= / (?! / (?i) 等)')
        index = None
        if capture:
            self.ngroups += 1
            index = self.ngroups
        body = self.alt()
        if self.peek() != ')':
            self.error('括号未闭合')
        self.i += 1
        return Group(index, body) if capture else body

    def _charclass(self):
        self.i += 1  # '['
        negated = False
        if self.peek() == '^':
            negated = True
            self.i += 1
        items = []
        first = True
        while True:
            c = self.peek()
            if c is None:
                raise ParseError('字符类未闭合(缺少 "]")')
            if c == ']' and not first:
                self.i += 1
                break
            first = False
            # 读入一个类内元素(可能是转义)
            if c == '\\':
                self.i += 1
                ranges = _escape_in_class(self.take())
            else:
                self.i += 1
                ranges = [(c, c)]
            lo, hi = ranges[-1] if len(ranges) == 1 else (None, None)
            if len(ranges) == 1 and lo is not None and \
                    self.peek() == '-' and self.peek(1) not in (None, ']'):
                # 可能是区间 a-z
                self.i += 1  # '-'
                c2 = self.peek()
                if c2 == '\\':
                    self.i += 1
                    r2 = _escape_in_class(self.take())
                    if len(r2) != 1:
                        self.error(r'类转义不能作为区间端点(如 [a-\d])')
                    hi_ch = r2[0][0]
                else:
                    self.i += 1
                    hi_ch = c2
                if ord(lo) > ord(hi_ch):
                    raise ParseError(f'字符区间反序: {lo}-{hi_ch}')
                items.append((lo, hi_ch))
            else:
                items.extend(ranges)
        return Class(items, negated)


def parse(pattern):
    """解析正则,返回 (ast, ngroups)。ngroups 为捕获分组个数。"""
    p = _Parser(pattern)
    ast = p.parse()
    return ast, p.ngroups


if __name__ == '__main__':
    import sys
    for pat in (sys.argv[1:] or [r'(a|b)+[0-9]{2,3}']):
        ast, n = parse(pat)
        print(f'{pat!r:30} groups={n}\n  {ast}')
