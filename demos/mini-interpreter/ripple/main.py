"""命令行入口。

用法(在 mini-interpreter 目录下):
    python -m ripple examples/fib.rip
    python -m ripple -e "print(1 + 2 * 3)"
"""

import sys

from .errors import RippleError
from .lexer import Lexer
from .parser import Parser
from .interpreter import Interpreter, RuntimeErr


def run_source(source, out=print):
    """跑一段源码:Lexer -> Parser -> Interpreter,任何 Ripple 错误抛给调用方。"""
    tokens = Lexer(source).tokenize()
    ast = Parser(tokens).parse()
    Interpreter(out=out).run(ast)


def main(argv):
    if len(argv) >= 2 and argv[1] == "-e":
        if len(argv) != 3:
            print('usage: python -m ripple -e "<code>"')
            return 2
        try:
            run_source(argv[2])
        except RippleError as e:
            print(e)
            return 1
        return 0

    if len(argv) != 2:
        print("usage: python -m ripple <file.rip>")
        print('       python -m ripple -e "<code>"')
        return 2

    path = argv[1]
    try:
        with open(path, "r", encoding="utf-8") as f:
            source = f.read()
    except OSError as e:
        print("cannot read %s: %s" % (path, e))
        return 2

    try:
        run_source(source)
    except RippleError as e:
        print(e)
        return 1
    except RecursionError:
        # 深度递归(如 fib 写错终止条件)会顶到 Python 的栈上限
        print("runtime error: recursion too deep (stack overflow)")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
