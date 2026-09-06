"""Tree-walking Interpreter:直接遍历 AST 求值,不做任何中间代码。

核心设计:
  - Environment 链实现词法作用域 + 块级作用域:
    每进入一个块/函数体/循环体就创建子环境;let 在当前环境声明,
    赋值沿父链向上找已有变量(找不到则报错)。
  - 闭包:Function 对象捕获「定义时」的环境,调用时以它为父环境,
    所以内层函数可以记住外层变量 —— 这是闭包的全部秘密。
  - return 用异常跳出多层调用栈。
"""

from .errors import RuntimeErr
from . import ast_nodes as A


# ---- 运行时值 ---------------------------------------------------------------


class Environment:
    def __init__(self, parent=None):
        self.vars = {}
        self.parent = parent

    def declare(self, name, value, line):
        """let:只在当前作用域声明(允许遮蔽外层同名变量)。"""
        self.vars[name] = value

    def assign(self, name, value, line):
        """=:沿作用域链找到已有变量并修改。"""
        env = self
        while env is not None:
            if name in env.vars:
                env.vars[name] = value
                return
            env = env.parent
        raise RuntimeErr("undefined variable '%s' (assign before let?)"
                         % name, line)

    def get(self, name, line):
        env = self
        while env is not None:
            if name in env.vars:
                return env.vars[name]
            env = env.parent
        raise RuntimeErr("undefined variable '%s'" % name, line)


class Function:
    """用户定义的函数值:函数体 + 定义时所在的环境(闭包捕获)。"""

    def __init__(self, name, params, body, closure_env):
        self.name = name or "<anonymous>"
        self.params = params
        self.body = body
        self.closure_env = closure_env

    def __repr__(self):
        return "<fn %s/%d>" % (self.name, len(self.params))


class Builtin:
    """内置函数(print 等)。"""

    def __init__(self, name, fn):
        self.name = name
        self.fn = fn

    def __repr__(self):
        return "<builtin %s>" % self.name


class _ReturnSignal(Exception):
    """用异常实现 return:从任意深度的函数体直接跳出。"""

    def __init__(self, value):
        self.value = value


# ---- 解释器 -----------------------------------------------------------------


class Interpreter:
    def __init__(self, out=None):
        self.globals = Environment()
        self._install_builtins()
        self.out = out if out is not None else print

    def _install_builtins(self):
        def bi_print(args, line):
            self.out(" ".join(format_value(a) for a in args))
            return None
        def bi_len(args, line):
            (v,) = self._arity("len", args, 1, line)
            if isinstance(v, (list, str)):
                return len(v)
            raise RuntimeErr("len() expects a list or string, got %s"
                             % type_name(v), line)
        def bi_str(args, line):
            (v,) = self._arity("str", args, 1, line)
            return format_value(v)
        def bi_int(args, line):
            (v,) = self._arity("int", args, 1, line)
            if isinstance(v, bool):
                return 1 if v else 0
            if isinstance(v, int):
                return v
            if isinstance(v, float):
                return int(v)
            if isinstance(v, str):
                try:
                    return int(v.strip())
                except ValueError:
                    raise RuntimeErr("cannot convert %r to int" % v, line)
            raise RuntimeErr("cannot convert %s to int" % type_name(v), line)
        self.globals.declare("print", Builtin("print", bi_print), 0)
        self.globals.declare("len", Builtin("len", bi_len), 0)
        self.globals.declare("str", Builtin("str", bi_str), 0)
        self.globals.declare("int", Builtin("int", bi_int), 0)

    @staticmethod
    def _arity(name, args, n, line):
        if len(args) != n:
            raise RuntimeErr("%s() expects %d argument(s), got %d"
                             % (name, n, len(args)), line)
        return args

    # ---- 入口 ---------------------------------------------------------------

    def run(self, program):
        self._exec_block(program.stmts, self.globals)

    def _exec_block(self, stmts, env):
        """在给定环境中顺序执行语句列表。

        注意:块的「新作用域」由调用方创建(if/while/函数体各自 new 一个
        子环境再调这里),这样全局顶层语句不会额外包一层。
        """
        for stmt in stmts:
            self._exec(stmt, env)

    # ---- 语句 ---------------------------------------------------------------

    def _exec(self, node, env):
        if isinstance(node, A.Let):
            env.declare(node.name, self._eval(node.value, env), node.line)
        elif isinstance(node, A.Assign):
            env.assign(node.name, self._eval(node.value, env), node.line)
        elif isinstance(node, A.ExprStmt):
            self._eval(node.expr, env)
        elif isinstance(node, A.If):
            branch = node.then_body if self._truthy(
                self._eval(node.cond, env)) else node.else_body
            if branch is not None:
                # 每个分支都是新块作用域
                self._exec_block(branch, Environment(env))
        elif isinstance(node, A.While):
            while self._truthy(self._eval(node.cond, env)):
                # 每次迭代新作用域:循环体内 let 不会累积到下一轮
                self._exec_block(node.body, Environment(env))
        elif isinstance(node, A.Return):
            value = None if node.value is None else self._eval(node.value, env)
            raise _ReturnSignal(value)
        elif isinstance(node, A.FnDecl):
            env.declare(node.name,
                        Function(node.name, node.params, node.body, env),
                        node.line)
        else:
            raise RuntimeErr("unknown statement %r" % node, getattr(node, "line", None))

    # ---- 表达式 ---------------------------------------------------------------

    def _eval(self, node, env):
        if isinstance(node, A.Num):
            return node.value
        if isinstance(node, A.Str):
            return node.value
        if isinstance(node, A.Bool):
            return node.value
        if isinstance(node, A.InterpStr):
            # 插值:各部分求值后转成字符串拼接
            return "".join(p if isinstance(p, str)
                           else format_value(self._eval(p, env))
                           for p in node.parts)
        if isinstance(node, A.ListLit):
            return [self._eval(item, env) for item in node.items]
        if isinstance(node, A.Var):
            return env.get(node.name, node.line)
        if isinstance(node, A.Unary):
            return self._unary(node, env)
        if isinstance(node, A.Logical):
            return self._logical(node, env)
        if isinstance(node, A.BinOp):
            return self._binop(node, env)
        if isinstance(node, A.Call):
            return self._call(node, env)
        if isinstance(node, A.Index):
            return self._index(node, env)
        if isinstance(node, A.FnExpr):
            return Function(None, node.params, node.body, env)
        raise RuntimeErr("unknown expression %r" % node,
                         getattr(node, "line", None))

    def _unary(self, node, env):
        v = self._eval(node.operand, env)
        if node.op == "-":
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                return -v
            raise RuntimeErr("unary '-' expects a number, got %s"
                             % type_name(v), node.line)
        # !
        return not self._truthy(v)

    def _logical(self, node, env):
        left = self._eval(node.left, env)
        # 短路:&& 左边为假 / || 左边为真 时不再求值右边;结果取左值
        if node.op == "&&":
            if not self._truthy(left):
                return left
        else:
            if self._truthy(left):
                return left
        return self._eval(node.right, env)

    def _binop(self, node, env):
        # 注意:除了 &&/||,其余运算符都先完整求值两边再运算
        l = self._eval(node.left, env)
        r = self._eval(node.right, env)
        op = node.op

        if op == "==":
            return self._equals(l, r)
        if op == "!=":
            return not self._equals(l, r)

        if op == "+":
            # + 双重语义:数字加法 / 字符串拼接
            if self._is_num(l) and self._is_num(r):
                return l + r
            if isinstance(l, str) and isinstance(r, str):
                return l + r
            raise RuntimeErr("'+' expects two numbers or two strings, got %s and %s"
                             % (type_name(l), type_name(r)), node.line)

        if op in ("-", "*", "/", "%"):
            if not (self._is_num(l) and self._is_num(r)):
                raise RuntimeErr("'%s' expects numbers, got %s and %s"
                                 % (op, type_name(l), type_name(r)), node.line)
            if op == "-":
                return l - r
            if op == "*":
                return l * r
            if op == "/":
                if r == 0:
                    raise RuntimeErr("division by zero", node.line)
                return l / r          # 真除法:int/int 得 float
            if op == "%":
                if r == 0:
                    raise RuntimeErr("modulo by zero", node.line)
                return l % r

        if op in ("<", "<=", ">", ">="):
            ok = (self._is_num(l) and self._is_num(r)) or \
                 (isinstance(l, str) and isinstance(r, str))
            if not ok:
                raise RuntimeErr("'%s' expects two numbers or two strings, got %s and %s"
                                 % (op, type_name(l), type_name(r)), node.line)
            if op == "<":
                return l < r
            if op == "<=":
                return l <= r
            if op == ">":
                return l > r
            return l >= r

        raise RuntimeErr("unknown operator '%s'" % op, node.line)

    def _call(self, node, env):
        callee = self._eval(node.callee, env)
        args = [self._eval(a, env) for a in node.args]

        if isinstance(callee, Builtin):
            return callee.fn(args, node.line)
        if isinstance(callee, Function):
            if len(args) != len(callee.params):
                raise RuntimeErr("%s() expects %d argument(s), got %d"
                                 % (callee.name, len(callee.params), len(args)),
                                 node.line)
            # 新环境:父环境是「定义时」的环境 —— 闭包语义在此
            call_env = Environment(callee.closure_env)
            for name, arg in zip(callee.params, args):
                call_env.declare(name, arg, node.line)
            try:
                self._exec_block(callee.body, call_env)
            except _ReturnSignal as ret:
                return ret.value
            return None               # 没走到 return -> nil
        raise RuntimeErr("value of type %s is not callable" % type_name(callee),
                         node.line)

    def _index(self, node, env):
        target = self._eval(node.target, env)
        idx = self._eval(node.index, env)
        if not isinstance(idx, int) or isinstance(idx, bool):
            raise RuntimeErr("index must be an int, got %s" % type_name(idx),
                             node.line)
        if isinstance(target, (list, str)):
            try:
                return target[idx]    # 字符串索引得到 1 字符串;list 得到元素
            except IndexError:
                raise RuntimeErr("index %d out of range (length %d)"
                                 % (idx, len(target)), node.line)
        raise RuntimeErr("cannot index into %s" % type_name(target), node.line)

    # ---- 辅助 ---------------------------------------------------------------

    @staticmethod
    def _is_num(v):
        return isinstance(v, (int, float)) and not isinstance(v, bool)

    @staticmethod
    def _truthy(v):
        # Lua 风格:只有 false 和 nil 为假,其余(含 0、"" )都为真
        return v is not None and v is not False

    @staticmethod
    def _equals(l, r):
        # bool 与 int 在 Python 中相等(1 == True),这里显式区分类型
        if isinstance(l, bool) or isinstance(r, bool):
            return isinstance(l, bool) and isinstance(r, bool) and l == r
        if Interpreter._is_num(l) and Interpreter._is_num(r):
            return l == r
        return type(l) is type(r) and l == r


# ---- 值的显示 ---------------------------------------------------------------


def type_name(v):
    if v is None:
        return "nil"
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, int):
        return "int"
    if isinstance(v, float):
        return "float"
    if isinstance(v, str):
        return "string"
    if isinstance(v, list):
        return "list"
    if isinstance(v, (Function, Builtin)):
        return "function"
    return type(v).__name__


def format_value(v):
    """把 Ripple 值转成用户可读的字符串(print / 插值 共用)。"""
    if v is None:
        return "nil"
    if v is True:
        return "true"
    if v is False:
        return "false"
    if isinstance(v, float):
        # 避免浮点尾差噪音:3.0000000000000004 这类保留,但 3.5 正常显示
        return repr(v)
    if isinstance(v, int):
        return str(v)
    if isinstance(v, str):
        return v
    if isinstance(v, list):
        return "[" + ", ".join(format_value(x) for x in v) + "]"
    if isinstance(v, (Function, Builtin)):
        return repr(v)
    return str(v)
