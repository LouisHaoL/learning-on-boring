"""统一的三类错误:词法错误 / 语法错误 / 运行时错误,全部携带行号。"""


class RippleError(Exception):
    """所有 Ripple 错误的基类。line 为出错处源码行号(从 1 开始)。"""

    def __init__(self, message, line=None):
        super().__init__(message)
        self.message = message
        self.line = line

    def __str__(self):
        if self.line is not None:
            return "[line %d] %s" % (self.line, self.message)
        return self.message


class LexError(RippleError):
    """词法阶段错误:非法字符、未闭合的字符串/插值等。"""


class ParseError(RippleError):
    """语法阶段错误:不符合文法的 token 序列。"""


class RuntimeErr(RippleError):
    """解释执行阶段的错误:类型不匹配、未定义变量、除零等。"""
