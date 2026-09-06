"""Token 定义。

token.type 用普通字符串(可读性好、零样板),约定:
  - 单字符/双字符运算符直接用字面量,如 "+", "<=", "&&"
  - 关键字用大写名,如 "let", "fn", "if"
  - 其他: "ident", "int", "float", "string", "eof"

Token.value:
  - "int"/"float" -> int/float
  - "string"      -> str(无插值)或 list(有插值;元素为 str 或 list[Token])
"""


class Token:
    __slots__ = ("type", "value", "line")

    def __init__(self, type_, value, line):
        self.type = type_
        self.value = value
        self.line = line

    def __repr__(self):
        return "Token(%s, %r, line=%d)" % (self.type, self.value, self.line)


KEYWORDS = {"let", "fn", "if", "else", "while", "true", "false", "return"}

# 双字符运算符必须先于单字符匹配,否则 "<=" 会被切成 "<" 和 "="
TWO_CHAR_OPS = {"==", "!=", "<=", ">=", "&&", "||"}
ONE_CHAR_OPS = set("+-*/%(){}[],=<>!;")


def is_keyword(text):
    return text in KEYWORDS
