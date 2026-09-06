# Ripple —— 一个用 Python 从零实现的小型解释器

Ripple 是一个为学习解释器原理而写的小型解释型语言,零依赖、纯 Python 标准库实现。
流水线:**Lexer → Parser(递归下降)→ AST → Tree-walking Interpreter**。

## 如何运行

```bash
cd demos/mini-interpreter

# 跑一个 .rip 源文件
python -m ripple examples/fib.rip

# 直接执行一段代码
python -m ripple -e "print(1 + 2 * 3)"

# 跑测试套件(25 项断言,覆盖 Lexer / Parser / Interpreter / 示例端到端)
python tests.py
```

环境要求:Python 3.8+(代码里用了海象运算符 `:=`)。无任何第三方依赖。

## 语言速览

```text
// Ripple 用 # 做行注释(这里为排版用 // 示意,实际请看 examples/ 下的源码)

let x = 10;            # 变量声明(let 只在当前块作用域生效)
x = x + 1;             # 赋值(沿作用域链找到已有变量再改)

1, 2.5, "hello", true  # 整数 / 浮点 / 字符串 / 布尔
[1, 2, 3]              # 列表字面量,xs[0] 索引(字符串也能索引)
"name = ${n}!"         # 字符串插值,${} 里是任意表达式

1 + 2 * 3 <= 7 && !(a == b) || c   # 算术/比较/逻辑,含优先级,&& || 短路

if n % 15 == 0 { print("FizzBuzz"); }
else if n % 3 == 0 { print("Fizz"); }
else { print(n); }

while i < 10 { i = i + 1; }

fn fib(n) {                        # 命名函数声明
    if n <= 1 { return n; }
    return fib(n - 1) + fib(n - 2);
}

let inc  = fn(x) { return x + 1; };   # 匿名函数表达式
let add5 = make_adder(5);             # 工厂函数返回闭包(见 examples/closures.rip)

print("fib(10) =", fib(10));       # 内置:print / len / str / int
```

语义要点:

- **块级作用域**:每个 `{}` 块、函数体、每轮循环体都是新作用域;`let` 声明在当前作用域(允许遮蔽外层),`=` 赋值沿作用域链向上找已有变量。
- **`/` 是真除法**:`10 / 4` 得 `2.5`;`%` 取模;除零是带行号的运行时错误。
- **真值**:只有 `false` 和 `nil` 为假(Lua 风格),`0`、`""` 都为真。
- **函数**:定义时捕获所在环境(闭包);没执行到 `return` 就返回 `nil`。
- `&&` / `||` 短路且返回操作数值本身(和 Python 一致)。

## 架构说明

```text
源码 (.rip)
   │  ripple/lexer.py      字符流 → Token 流
   ▼
[Token]                    ripple/tokens.py   Token / 关键字 / 运算符表
   │  ripple/parser.py     Token 流 → AST(递归下降)
   ▼
[AST]                      ripple/ast_nodes.py 纯数据节点(带行号)
   │  ripple/interpreter.py 遍历 AST 直接求值
   ▼
输出
```

### Lexer(`ripple/lexer.py`)—— 词法分析

职责只有一个:把字符串切成 token 流,丢弃空白和 `#` 注释,并给每个 token 记录行号。

- 数字:`123` → int,`1.5` → float(点后必须是数字,`1.foo` 不算浮点)。
- 标识符/关键字:扫完整个词再查关键字表;关键字的 token type 就是关键字本身,方便 Parser 判断。
- 运算符:先试双字符(`==` `<=` `&&`…)再试单字符,否则 `<=` 会被切成 `<` 和 `=`。
- **字符串插值**:遇到 `${` 时,把插值体(到配对 `}` 为止,内部括号深度被跟踪)递归交给一个新的 `Lexer`,得到的子 token 列表作为字符串值的一部分。Parser 拿到后再递归下降生成子表达式。
- 所有非法字符、未闭合字符串都抛 `LexError` 并带行号。

### Parser(`ripple/parser.py`)—— 语法分析(递归下降)

职责:按文法把 token 流组织成 AST。文法不用写下来,直接编码在函数调用结构里。

**运算符优先级的处理**(文件头注释里有完整说明):每一级优先级对应一个解析函数,链条从松到紧:

```text
parse_or → parse_and → parse_equality → parse_comparison
        → parse_term(+ -) → parse_factor(* / %)
        → parse_unary(! -) → parse_call(调用/索引) → parse_primary
```

- 低优先级函数先被调用,它调用高一级的函数解析左操作数,再用 `while` 循环消耗自己这一级的运算符 —— **同级左结合靠 while,不同级优先靠调用层级**,所以 `1 + 2 * 3` 自然是 `1 + (2*3)`,`10 - 4 - 3` 是 `(10-4)-3`,`!a && b` 是 `(!a) && b`。
- `&&` / `||` 单独做成 `Logical` 节点(和 `BinOp` 区分),因为它们需要短路求值。
- 语句层:`let` / `fn name()` / `if`(支持 `else if` 链)/ `while` / `return` / 赋值 / 表达式语句。`fn` 后跟标识符解析为声明,后跟 `(` 则是匿名函数表达式。
- 语法错误(`ParseError`)带行号:`[line 2] expected ')' but got ';'`。

### AST(`ripple/ast_nodes.py`)

纯数据类,每个节点带 `line`。**节点不含行为,行为全在 Interpreter 里** —— 这是"数据与解释分离"的最简形态,也是后续做字节码/优化时可以保留的中间表示。

### Interpreter(`ripple/interpreter.py`)—— 树遍历求值

职责:直接递归遍历 AST 求值,不生成任何中间代码。

- **作用域**:`Environment` 是一个 `{名字: 值}` 加上 `parent` 指针的链表。进入块/函数体/循环体就 new 一个子环境;`let` 写当前环境,`get`/`assign` 沿 parent 链向上走。块级作用域、变量遮蔽都免费获得。
- **闭包**:函数值是 `Function(name, params, body, closure_env)` —— 关键在 `closure_env` 记录的是**定义时**的环境而非调用时的,调用时新环境的 parent 指向它,于是内层函数"记住"了外层变量。`examples/closures.rip` 的计数器就是靠这个。
- **return**:用异常 `_ReturnSignal` 从任意深度的语句块直接跳出函数体。
- **短路求值**:只在 `Logical` 求值时先算左边、必要时跳过右边。
- **类型检查**:每个运算符在求值后检查操作数类型,不匹配抛 `RuntimeErr` 并带行号(`[line 1] '+' expects two numbers or two strings, got string and int`)。
- 内置函数(`print` / `len` / `str` / `int`)就是装在全局环境里的 `Builtin` 对象。

## 完整示例

`examples/fib.rip`:

```text
# 递归:斐波那契数列
fn fib(n) {
    if n <= 1 {
        return n;
    }
    return fib(n - 1) + fib(n - 2);
}

let i = 0;
while i <= 10 {
    print("fib(" + str(i) + ") = " + str(fib(i)));
    i = i + 1;
}

print("fib(20) = " + str(fib(20)));
```

运行输出(`python -m ripple examples/fib.rip`,已实际验证):

```text
fib(0) = 0
fib(1) = 1
fib(2) = 1
fib(3) = 2
fib(4) = 3
fib(5) = 5
fib(6) = 8
fib(7) = 13
fib(8) = 21
fib(9) = 34
fib(10) = 55
fib(20) = 6765
```

## 示例程序(examples/,均已运行验证)

| 文件 | 演示内容 |
|---|---|
| `examples/fib.rip` | 递归函数、if/else、while |
| `examples/fizzbuzz.rip` | while 循环、取模、比较/逻辑运算符、else-if 链 |
| `examples/closures.rip` | 闭包、匿名函数、函数作为值/列表元素、高阶函数 compose |

`python -m ripple examples/fizzbuzz.rip` 输出(已验证):

```text
1
2
Fizz
4
Buzz
Fizz
7
8
Fizz
Buzz
11
Fizz
13
14
FizzBuzz
16
17
Fizz
19
Buzz
```

`python -m ripple examples/closures.rip` 输出(已验证,注释解释每行来源):

```text
11   # a() 第一次:闭包内 count 从 10 加到 11
12   # a() 第二次:同一个闭包,count 继续累积
1    # b() 第一次:make_counter 每次调用生成独立作用域
6    # add5(1) = 1 + 5
11   # add10(1) = 1 + 10
110  # ops[1](100):函数存在列表里,索引取出后调用
10   # compose(dbl, inc)(4) = (4+1)*2
```

## 目录结构

```text
mini-interpreter/
├── ripple/
│   ├── __init__.py
│   ├── __main__.py      # python -m ripple 入口
│   ├── main.py          # CLI:读文件 / -e 执行,统一错误出口
│   ├── tokens.py        # Token 类、关键字表、运算符表
│   ├── errors.py        # LexError / ParseError / RuntimeErr(统一带行号)
│   ├── lexer.py         # 阶段 1:词法分析(含字符串插值的子词法)
│   ├── ast_nodes.py     # 阶段 2.5:AST 节点(纯数据)
│   ├── parser.py        # 阶段 2:递归下降语法分析
│   └── interpreter.py   # 阶段 3:树遍历解释器(Environment/闭包/内置函数)
├── examples/
│   ├── fib.rip
│   ├── fizzbuzz.rip
│   └── closures.rip
├── tests.py             # 25 项断言的最小测试套件
└── README.md
```

## 测试

`tests.py` 不用任何测试框架,纯 `assert`:

```bash
python tests.py
# ...
# all 25 checks passed
```

覆盖点包括:token 切分与行号、多字符运算符不被拆散、运算符优先级生成的 AST 形状(含左结合与括号)、块级作用域与变量遮蔽、短路求值、递归与早退、闭包捕获定义环境、列表/字符串索引、内置函数、`==` 的类型区分(如 `1 == true` 为 false),以及三类错误都带正确行号。

## 加分项实现情况

- **字符串插值**:`"n=${n}, n*2=${n * 2}!"`,Lexer 递归子词法 + Parser 递归子解析,支持任意表达式。
- **数组字面量与索引**:`[1, 2, [3, 4]]`、嵌套索引 `xs[3][1]`、字符串索引 `"hi"[0]`,越界有行号报错。
- **带行号的错误报告**:词法/语法/运行时三类错误统一格式 `[line N] message`。
