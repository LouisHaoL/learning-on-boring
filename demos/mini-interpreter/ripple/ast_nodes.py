"""AST 节点定义(纯数据,不含行为;行为在 Interpreter 里)。

每个节点带 line,供运行时报错定位。
表达式(Expression)与语句(Statement)只是概念区分,统一用普通类。
"""

# ---- 表达式 ----------------------------------------------------------------


class Num:
    def __init__(self, value, line):
        self.value = value  # int 或 float
        self.line = line


class Str:
    def __init__(self, value, line):
        self.value = value  # 普通字符串字面量
        self.line = line


class Bool:
    def __init__(self, value, line):
        self.value = value  # True / False
        self.line = line


class ListLit:
    def __init__(self, items, line):
        self.items = items  # list[expr]
        self.line = line


class InterpStr:
    def __init__(self, parts, line):
        self.parts = parts  # list[str | expr],插值字符串


class Var:
    def __init__(self, name, line):
        self.name = name
        self.line = line


class BinOp:
    def __init__(self, op, left, right, line):
        self.op = op        # "+", "-", "*", "/", "%", "==", "!=", "<", "<=", ">", ">="
        self.left = left
        self.right = right
        self.line = line


class Unary:
    def __init__(self, op, operand, line):
        self.op = op        # "-" 或 "!"
        self.operand = operand
        self.line = line


class Logical:
    def __init__(self, op, left, right, line):
        self.op = op        # "&&" / "||"(短路求值,故与 BinOp 分开)
        self.left = left
        self.right = right
        self.line = line


class Call:
    def __init__(self, callee, args, line):
        self.callee = callee
        self.args = args    # list[expr]
        self.line = line


class Index:
    def __init__(self, target, index, line):
        self.target = target  # list 或 string
        self.index = index
        self.line = line


class FnExpr:
    """匿名函数表达式: fn(x, y) { ... }"""

    def __init__(self, params, body, line):
        self.params = params  # list[str]
        self.body = body      # list[stmt]
        self.line = line


# ---- 语句 ------------------------------------------------------------------


class Let:
    def __init__(self, name, value, line):
        self.name = name
        self.value = value
        self.line = line


class Assign:
    def __init__(self, name, value, line):
        self.name = name
        self.value = value
        self.line = line


class ExprStmt:
    def __init__(self, expr):
        self.expr = expr


class If:
    def __init__(self, cond, then_body, else_body, line):
        self.cond = cond
        self.then_body = then_body  # list[stmt]
        self.else_body = else_body  # list[stmt] | None
        self.line = line


class While:
    def __init__(self, cond, body, line):
        self.cond = cond
        self.body = body  # list[stmt]
        self.line = line


class Return:
    def __init__(self, value, line):
        self.value = value  # expr | None
        self.line = line


class FnDecl:
    """命名函数声明: fn fib(n) { ... }(本质是 let fib = fn 表达式的语法糖)"""

    def __init__(self, name, params, body, line):
        self.name = name
        self.params = params
        self.body = body
        self.line = line


class Program:
    def __init__(self, stmts):
        self.stmts = stmts
