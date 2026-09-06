"""Lexer(词法分析器):把源码字符串切成 token 流。

职责:
  - 识别数字(int/float)、标识符/关键字、字符串(含转义与 ${...} 插值)、运算符
  - 记录每个 token 的行号,供后续语法/运行时报错使用
  - 丢弃空白与 # 注释

字符串插值的处理方式:遇到 "${" 时,对插值体(到匹配的 "}" 为止)
递归调用 Lexer 得到子 token 列表,作为字符串 value 的一部分保存。
Parser 拿到后再对子 token 列表递归下降,生成子表达式 AST。
"""

from .errors import LexError
from .tokens import Token, KEYWORDS, TWO_CHAR_OPS, ONE_CHAR_OPS

ESCAPES = {"n": "\n", "t": "\t", '"': '"', "\\": "\\", "$": "$"}


class Lexer:
    def __init__(self, source, base_line=1):
        self.src = source
        self.pos = 0
        self.line = base_line          # 当前行号(1-based)
        self.base_line = base_line     # 插值子词法器继承外层行号用

    # ---- 基础工具 -------------------------------------------------------

    def _peek(self):
        return self.src[self.pos] if self.pos < len(self.src) else "\0"

    def _peek_next(self):
        i = self.pos + 1
        return self.src[i] if i < len(self.src) else "\0"

    def _advance(self):
        ch = self.src[self.pos]
        self.pos += 1
        if ch == "\n":
            self.line += 1
        return ch

    def _error(self, msg, line=None):
        raise LexError(msg, line if line is not None else self.line)

    # ---- 主入口 ---------------------------------------------------------

    def tokenize(self):
        tokens = []
        while self.pos < len(self.src):
            ch = self._peek()
            if ch in " \t\r\n":
                self._advance()
            elif ch == "#":                      # 注释:到行尾
                while self.pos < len(self.src) and self._peek() != "\n":
                    self._advance()
            elif ch.isdigit():
                tokens.append(self._number())
            elif ch.isalpha() or ch == "_":
                tokens.append(self._identifier())
            elif ch == '"':
                tokens.append(self._string())
            else:
                tokens.append(self._operator())
        tokens.append(Token("eof", None, self.line))
        return tokens

    # ---- 各类 token ------------------------------------------------------

    def _number(self):
        line = self.line
        start = self.pos
        while self._peek().isdigit():
            self._advance()
        is_float = False
        # "1.5" 是浮点;"1.foo" / "1." 不是(点后必须是数字)
        if self._peek() == "." and self._peek_next().isdigit():
            is_float = True
            self._advance()
            while self._peek().isdigit():
                self._advance()
        text = self.src[start:self.pos]
        return Token("float" if is_float else "int",
                     float(text) if is_float else int(text), line)

    def _identifier(self):
        line = self.line
        start = self.pos
        while self._peek().isalnum() or self._peek() == "_":
            self._advance()
        text = self.src[start:self.pos]
        # 关键字直接用关键字本身作为 type,parser 好判断
        return Token(text if text in KEYWORDS else "ident", text, line)

    def _string(self):
        line = self.line            # 字符串起始行
        self._advance()             # 吃掉开头的 "
        parts = []                  # 元素: str 纯文本 | list[Token] 插值表达式
        buf = []

        def flush():
            if buf:
                parts.append("".join(buf))
                buf.clear()

        while True:
            if self.pos >= len(self.src):
                self._error("unterminated string (missing closing '\"')", line)
            ch = self._advance()
            if ch == '"':
                break
            if ch == "\\":
                esc = self._peek()
                if esc not in ESCAPES:
                    self._error("unknown escape '\\%s'" % esc)
                self._advance()
                buf.append(ESCAPES[esc])
            elif ch == "$" and self._peek() == "{":
                self._advance()     # 吃掉 '{'
                flush()
                parts.append(self._interpolation(line))
            else:
                buf.append(ch)
        flush()
        # 无插值时退化为普通 str,AST 更简单
        if len(parts) == 1 and isinstance(parts[0], str):
            return Token("string", parts[0], line)
        return Token("string", parts, line)

    def _interpolation(self, base_line):
        """扫描 ${...} 内部,返回其中内容的子 token 列表。"""
        depth = 0
        start = self.pos
        while True:
            if self.pos >= len(self.src):
                self._error("unterminated interpolation (missing '}')", base_line)
            ch = self._peek()
            if ch in "([{":
                depth += 1
            elif ch in ")]}":
                if depth == 0:
                    break           # 这是插值的收尾 '}'
                depth -= 1
            self._advance()
        inner = self.src[start:self.pos]
        self._advance()             # 吃掉 '}'
        # 递归词法;子 token 行号叠加外层字符串的起始行
        sub = Lexer(inner, base_line=base_line).tokenize()
        sub.pop()                   # 去掉子词法器加的 eof
        return sub

    def _operator(self):
        line = self.line
        two = self.src[self.pos:self.pos + 2]
        if two in TWO_CHAR_OPS:
            self.pos += 2
            return Token(two, two, line)
        ch = self._advance()
        if ch in ONE_CHAR_OPS:
            return Token(ch, ch, line)
        self._error("unexpected character %r" % ch, line)
