# -*- coding: utf-8 -*-
"""Ripple 最小测试集:不依赖测试框架,直接 assert。

运行(在 mini-interpreter 目录下):
    python tests.py

覆盖三层:Lexer / Parser / Interpreter,外加带行号的错误报告。
"""

import io
import sys

from ripple.errors import LexError, ParseError, RuntimeErr
from ripple.lexer import Lexer
from ripple.parser import Parser
from ripple.interpreter import Interpreter
from ripple import ast_nodes as A

PASS = 0


def ok(name):
    global PASS
    PASS += 1
    print("  ok - %s" % name)


# ---------- 辅助 ---------------------------------------------------------------

def lex(src):
    return Lexer(src).tokenize()

def parse(src):
    return Parser(lex(src)).parse()

def run(src):
    """跑一段源码,返回 (捕获的 stdout 列表, 全局环境)。"""
    buf = io.StringIO()
    interp = Interpreter(out=lambda s: buf.write(s + "\n"))
    interp.run(parse(src))
    return buf.getvalue().splitlines(), interp

def eval_expr(expr_src):
    """把一个表达式包成程序跑,返回其打印值(单行)。"""
    out, _ = run('print(%s);' % expr_src)
    return out[0]

def expect_error(exc_cls, src, name, line=None):
    try:
        run(src)
    except exc_cls as e:
        assert isinstance(e, exc_cls), e
        if line is not None:
            assert e.line == line, "%s: expected line %d, got %s" % (name, line, e)
        ok("%s (line=%s)" % (name, e.line))
        return
    raise AssertionError("%s: no error raised" % name)


# ---------- Lexer ---------------------------------------------------------------

def test_lexer():
    print("[lexer]")
    toks = lex('let x = 1.5; # comment\nx = "hi\\n" + "${x}";')
    types = [t.type for t in toks]
    assert types == ["let", "ident", "=", "float", ";", "ident", "=",
                     "string", "+", "string", ";", "eof"], types
    assert toks[3].value == 1.5 and toks[3].line == 1
    assert toks[5].value == "x" and toks[5].line == 2   # 行号正确
    assert toks[7].value == "hi\n"                       # 转义
    interp_tok = toks[9]
    assert isinstance(interp_tok.value, list)            # 插值 -> parts 列表
    assert isinstance(interp_tok.value[0], list)         # 开头无文本 -> 直接是子 token
    assert [t.type for t in interp_tok.value[0]] == ["ident"]
    ok("token types / numbers / escapes / line numbers")

    toks = lex("a <= b == c != d && e || !f % g")
    assert [t.type for t in toks] == [
        "ident", "<=", "ident", "==", "ident", "!=", "ident",
        "&&", "ident", "||", "!", "ident", "%", "ident", "eof"]
    ok("multi-char operators not split")

    try:
        lex('let s = "abc')
        raise AssertionError("unterminated string should raise")
    except LexError as e:
        assert e.line == 1
    ok("unterminated string raises LexError with line")


# ---------- Parser ---------------------------------------------------------------

def test_parser():
    print("[parser]")

    # 优先级: 1 + 2 * 3 -> 1 + (2 * 3)
    ast = parse("1 + 2 * 3;")
    expr = ast.stmts[0].expr
    assert isinstance(expr, A.BinOp) and expr.op == "+"
    assert isinstance(expr.right, A.BinOp) and expr.right.op == "*"
    assert expr.left.value == 1 and expr.right.left.value == 2

    # 左结合: 10 - 4 - 3 -> (10 - 4) - 3
    expr = parse("10 - 4 - 3;").stmts[0].expr
    assert isinstance(expr.left, A.BinOp) and expr.left.op == "-"

    # 括号改变结合:(1 + 2) * 3
    expr = parse("(1 + 2) * 3;").stmts[0].expr
    assert expr.op == "*" and isinstance(expr.left, A.BinOp)

    # 比较低于算术:n % 15 == 0 -> == 的左边是 %
    expr = parse("n % 15 == 0;").stmts[0].expr
    assert expr.op == "==" and expr.left.op == "%"

    # 逻辑优先级:a || b && c -> || 在顶层
    expr = parse("a || b && c;").stmts[0].expr
    assert isinstance(expr, A.Logical) and expr.op == "||"
    assert isinstance(expr.right, A.Logical)

    # 一元:-x * 2 -> (-x) * 2;!a && b -> (!a) && b
    expr = parse("-x * 2;").stmts[0].expr
    assert expr.op == "*" and isinstance(expr.left, A.Unary)
    expr = parse("!a && b;").stmts[0].expr
    assert expr.op == "&&" and isinstance(expr.left, A.Unary)

    # 调用与索引链:f(1)[2] -> Index(Call(f,1), 2)? 不 —— call/index 自左向右:
    # f(1)[2] 应是 Index(Call(f,[1]), 2)
    expr = parse("f(1)[2];").stmts[0].expr
    assert isinstance(expr, A.Index) and isinstance(expr.target, A.Call)

    ok("operator precedence builds the right tree")

    # else-if 链、匿名 fn、插值 AST
    ast = parse("""
    if a { } else if b { } else { }
    fn add(x, y) { return x + y; }
    let s = "n=${1+2}!";
    """)
    if_stmt = ast.stmts[0]
    assert isinstance(if_stmt, A.If) and len(if_stmt.else_body) == 1 \
        and isinstance(if_stmt.else_body[0], A.If)
    assert isinstance(ast.stmts[1], A.FnDecl) and ast.stmts[1].params == ["x", "y"]
    interp = ast.stmts[2].value
    assert isinstance(interp, A.InterpStr)
    assert isinstance(interp.parts[1], A.BinOp)
    ok("if/else-if, fn decl, interpolated string AST")

    try:
        parse("let x = ;")
        raise AssertionError("should raise")
    except ParseError as e:
        assert e.line == 1
    try:
        parse("if x { print(1);")
        raise AssertionError("should raise")
    except ParseError as e:
        assert e.line == 1 and "}" in str(e)
    ok("ParseError with line numbers")


# ---------- Interpreter -----------------------------------------------------------

def test_interpreter():
    print("[interpreter]")
    # 字面量与算术(含优先级)
    assert eval_expr("1 + 2 * 3") == "7"
    assert eval_expr("(1 + 2) * 3") == "9"
    assert eval_expr("10 / 4") == "2.5"          # 真除法 -> float
    assert eval_expr("7 % 3") == "1"
    assert eval_expr("-2 * 3") == "-6"
    assert eval_expr("1 + 2.5") == "3.5"
    ok("arithmetic & precedence")

    # 字符串 / 布尔 / 插值
    assert eval_expr('"a" + "b"') == "ab"
    assert eval_expr("1 == 1 && 2 != 3") == "true"
    assert eval_expr("!(1 > 2) || false") == "true"
    assert eval_expr('false && crash_boom') == "false"   # && 短路,右边不求值
    assert eval_expr('true || crash_boom') == "true"     # || 短路
    out, _ = run('let n = 42; print("n=${n}, n*2=${n * 2}!");')
    assert out == ["n=42, n*2=84!"], out
    ok("strings, booleans, short-circuit, interpolation")

    # 变量与块级作用域
    out, _ = run("""
    let x = 1;
    if true {
        let x = 100;    # 内层块遮蔽外层
        print(x);
        x = 101;        # 改的是内层
        print(x);
    }
    print(x);           # 外层不受影响
    x = 2;              # 赋值沿作用域链找到外层
    print(x);
    """)
    assert out == ["100", "101", "1", "2"], out
    expect_error(RuntimeErr, "y = 1;", "assign to undefined var")
    ok("block scoping: shadowing, assignment walks scope chain")

    # if / while
    out, _ = run("""
    let i = 0;
    let acc = 0;
    while i < 5 {
        let step = i * 10;   # 每轮迭代的新作用域
        acc = acc + step;
        i = i + 1;
    }
    print(acc);
    """)
    assert out == ["100"], out  # 0+10+20+30+40
    ok("while loop with per-iteration scope")

    # 函数、递归、return
    out, _ = run("""
    fn fact(n) {
        if n <= 1 { return 1; }
        return n * fact(n - 1);
    }
    print(fact(10));
    fn early(n) {
        if n > 0 { return "pos"; }
        return "non-pos";
    }
    print(early(5));
    print(early(0 - 1));
    fn noret() { let a = 1; }
    print(noret());
    """)
    assert out == ["3628800", "pos", "non-pos", "nil"], out
    ok("recursion, early return, missing-return -> nil")

    # 闭包:计数器 + 高阶函数
    out, _ = run("""
    fn make_counter(start) {
        let count = start;
        return fn() { count = count + 1; return count; };
    }
    let a = make_counter(0);
    let b = make_counter(100);
    a(); a();
    print(a());
    print(b());
    fn apply(f, x) { return f(x); }
    print(apply(fn(v) { return v * v; }, 9));
    """)
    assert out == ["3", "101", "81"], out
    ok("closures capture defining environment")

    # 列表与索引
    out, _ = run("""
    let xs = [1, 2, 3, [4, 5]];
    print(xs[0] + xs[1]);
    print(xs[3][1]);
    print(len(xs));
    print("hello"[1]);
    """)
    assert out == ["3", "5", "4", "e"], out
    ok("list literal, indexing, len, string index")

    # 内置函数
    assert eval_expr('len("abc") + len([1,2])') == "5"
    assert eval_expr('int("42") + int(3.9)') == "45"
    assert eval_expr('str(true) + "!"') == "true!"
    ok("builtins: len / str / int")

    # == 的类型区分:1 != true
    assert eval_expr("1 == true") == "false"
    assert eval_expr("true == true") == "true"
    assert eval_expr('"1" == 1') == "false"
    ok("equality distinguishes bool/int/string")

    # 运行时错误行号
    expect_error(RuntimeErr, "print(1);\nprint(2);\nprint(1 / 0);",
                 "division by zero", line=3)
    expect_error(RuntimeErr, "print(nope);", "undefined variable", line=1)
    expect_error(RuntimeErr, "fn f() { return 1; }\nlet x = f + 1;",
                 "non-callable", line=2)
    expect_error(RuntimeErr, 'let xs = [1];\nprint(xs[5]);',
                 "index out of range", line=2)
    expect_error(RuntimeErr, 'print(1 + "a");', "type error", line=1)
    ok("RuntimeErr carries line numbers")


# ---------- 端到端:跑示例程序 ------------------------------------------------------

def test_examples():
    print("[examples]")
    import subprocess
    for name, tail in [("fib.rip", "6765"), ("fizzbuzz.rip", "Buzz"),
                       ("closures.rip", "10")]:
        r = subprocess.run(
            [sys.executable, "-m", "ripple", "examples/" + name],
            capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        assert tail in r.stdout
        ok("%s runs clean" % name)


if __name__ == "__main__":
    test_lexer()
    test_parser()
    test_interpreter()
    test_examples()
    print("\nall %d checks passed" % PASS)
