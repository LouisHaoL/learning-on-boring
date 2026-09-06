"""Parser(语法分析器):递归下降,把 token 流构造成 AST。

运算符优先级的处理方式:每级优先级对应一个解析函数,
优先级越低(结合越松)的函数越早被调用、越靠近调用栈顶部:

    or        ->  parse_or
    and       ->  parse_and
    equality  ->  parse_equality        (== !=)
    comparison->  parse_comparison      (< <= > >=)
    term      ->  parse_term            (+ -)
    factor    ->  parse_factor          (* / %)
    unary     ->  parse_unary           (! -)
    call/index->  parse_call            (f(x), a[i], 左结合链式)
    primary   ->  parse_primary         (字面量/变量/括号/匿名fn/列表)

每个二元运算函数先调用「优先级更高的那个函数」解析左操作数,
再在自己的循环里消耗同级运算符 —— 同级靠 while 循环实现左结合。
这样 `1 + 2 * 3` 自然变成 `1 + (2 * 3)`,`a - b - c` 变成 `(a - b) - c`。
"""

from .errors import ParseError
from .tokens import Token
from . import ast_nodes as A

# 关键字 token 类型集合
STMT_KEYWORDS = {"let", "if", "while", "return", "fn"}


class Parser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0

    # ---- token 工具 -------------------------------------------------------

    def _peek(self):
        return self.tokens[self.pos]

    def _advance(self):
        tok = self.tokens[self.pos]
        self.pos += 1
        return tok

    def _check(self, type_):
        return self._peek().type == type_

    def _match(self, *types):
        if self._peek().type in types:
            return self._advance()
        return None

    def _expect(self, type_, what=None):
        tok = self._peek()
        if tok.type != type_:
            expected = what or "'%s'" % type_
            got = tok.value if tok.type != "eof" else "end of input"
            raise ParseError("expected %s but got '%s'" % (expected, got),
                             tok.line)
        return self._advance()

    # ---- 入口 ---------------------------------------------------------------

    def parse(self):
        stmts = []
        while not self._check("eof"):
            stmts.append(self._statement())
        return A.Program(stmts)

    # ---- 语句 ----------------------------------------------------------------

    def _statement(self):
        tok = self._peek()
        if tok.type == "let":
            return self._let_statement()
        if tok.type == "fn":
            return self._fn_statement()
        if tok.type == "if":
            return self._if_statement()
        if tok.type == "while":
            return self._while_statement()
        if tok.type == "return":
            return self._return_statement()
        return self._expr_or_assign_statement()

    def _let_statement(self):
        kw = self._advance()  # let
        name = self._expect("ident", "a variable name").value
        self._expect("=", "'=' after 'let %s'" % name)
        value = self._expression()
        self._optional_semi()
        return A.Let(name, value, kw.line)

    def _fn_statement(self):
        # "fn name(...)" 是声明;"fn(...)" 开头则是匿名函数表达式语句
        if self.tokens[self.pos + 1].type == "ident":
            kw = self._advance()  # fn
            name = self._advance().value
            params = self._params()
            body = self._block()
            return A.FnDecl(name, params, body, kw.line)
        expr = self._expression()
        self._optional_semi()
        return A.ExprStmt(expr)

    def _if_statement(self):
        kw = self._advance()  # if
        cond = self._expression()
        then_body = self._block()
        else_body = None
        if self._match("else"):
            if self._check("if"):       # else if 链
                else_body = [self._if_statement()]
            else:
                else_body = self._block()
        return A.If(cond, then_body, else_body, kw.line)

    def _while_statement(self):
        kw = self._advance()  # while
        cond = self._expression()
        body = self._block()
        return A.While(cond, body, kw.line)

    def _return_statement(self):
        kw = self._advance()  # return
        value = None
        # 行尾(或 '}' 前)视为 return 无值
        if not (self._check("eof") or self._check("}") or self._check(";")):
            value = self._expression()
        self._optional_semi()
        return A.Return(value, kw.line)

    def _expr_or_assign_statement(self):
        tok = self._peek()
        # 唯一的赋值形态: ident = expr(索引赋值不支持,保持语言最小)
        if tok.type == "ident" and self.tokens[self.pos + 1].type == "=":
            name_tok = self._advance()
            self._advance()  # '='
            value = self._expression()
            self._optional_semi()
            return A.Assign(name_tok.value, value, name_tok.line)
        expr = self._expression()
        self._optional_semi()
        return A.ExprStmt(expr)

    def _optional_semi(self):
        self._match(";")

    def _block(self):
        """块 = '{' stmt* '}'。if/while/fn 的体都要求花括号,避免悬垂歧义。"""
        self._expect("{", "'{'")
        stmts = []
        while not self._check("}"):
            if self._check("eof"):
                raise ParseError("unexpected end of input, missing '}'",
                                 self._peek().line)
            stmts.append(self._statement())
        self._advance()  # '}'
        return stmts

    def _params(self):
        self._expect("(", "'('")
        names = []
        if not self._check(")"):
            while True:
                names.append(self._expect("ident", "a parameter name").value)
                if not self._match(","):
                    break
        self._expect(")", "')'")
        return names

    # ---- 表达式:优先级从低到高 ---------------------------------------------

    def _expression(self):
        return self._or()

    def _or(self):
        left = self._and()
        while tok := self._match("||"):
            right = self._and()
            left = A.Logical("||", left, right, tok.line)
        return left

    def _and(self):
        left = self._equality()
        while tok := self._match("&&"):
            right = self._equality()
            left = A.Logical("&&", left, right, tok.line)
        return left

    def _equality(self):
        left = self._comparison()
        while tok := self._match("==", "!="):
            right = self._comparison()
            left = A.BinOp(tok.type, left, right, tok.line)
        return left

    def _comparison(self):
        left = self._term()
        while tok := self._match("<", "<=", ">", ">="):
            right = self._term()
            left = A.BinOp(tok.type, left, right, tok.line)
        return left

    def _term(self):
        left = self._factor()
        while tok := self._match("+", "-"):
            right = self._factor()
            left = A.BinOp(tok.type, left, right, tok.line)
        return left

    def _factor(self):
        left = self._unary()
        while tok := self._match("*", "/", "%"):
            right = self._unary()
            left = A.BinOp(tok.type, left, right, tok.line)
        return left

    def _unary(self):
        tok = self._match("!", "-")
        if tok:
            return A.Unary(tok.type, self._unary(), tok.line)
        return self._call()

    def _call(self):
        expr = self._primary()
        while True:
            if self._match("("):
                args = []
                if not self._check(")"):
                    while True:
                        args.append(self._expression())
                        if not self._match(","):
                            break
                close = self._expect(")", "')'")
                expr = A.Call(expr, args, close.line)
            elif self._match("["):
                index = self._expression()
                close = self._expect("]", "']'")
                expr = A.Index(expr, index, close.line)
            else:
                return expr

    def _primary(self):
        tok = self._peek()

        if tok.type in ("int", "float"):
            self._advance()
            return A.Num(tok.value, tok.line)
        if tok.type == "string":
            self._advance()
            if isinstance(tok.value, list):        # 带插值:parts 混有子 token 列表
                parts = [p if isinstance(p, str) else self._sub_expression(p)
                         for p in tok.value]
                return A.InterpStr(parts, tok.line)
            return A.Str(tok.value, tok.line)
        if tok.type == "true":
            self._advance()
            return A.Bool(True, tok.line)
        if tok.type == "false":
            self._advance()
            return A.Bool(False, tok.line)
        if tok.type == "ident":
            self._advance()
            return A.Var(tok.value, tok.line)
        if tok.type == "fn":
            self._advance()
            params = self._params()
            body = self._block()
            return A.FnExpr(params, body, tok.line)
        if tok.type == "[":
            return self._list_literal()
        if tok.type == "(":
            self._advance()
            expr = self._expression()
            self._expect(")", "')'")
            return expr

        got = tok.value if tok.type != "eof" else "end of input"
        raise ParseError("unexpected token '%s'" % got, tok.line)

    def _list_literal(self):
        open_ = self._advance()  # '['
        items = []
        if not self._check("]"):
            while True:
                items.append(self._expression())
                if not self._match(","):
                    break
        self._expect("]", "']'")
        return A.ListLit(items, open_.line)

    def _sub_expression(self, tokens):
        """解析插值里的子 token 列表(为它们新开一个 Parser)。"""
        sub = Parser(tokens + [Token("eof", None, tokens[-1].line
                                       if tokens else 1)])
        return sub._expression()
