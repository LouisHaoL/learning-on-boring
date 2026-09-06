# learning-on-boring

> 无聊的时候学点东西。由 AI 子 agent 并发学习,主 agent 规划方向、审查产出。
> 每一轮的学习内容、交付物与时间记录在本 README,细节链接到对应目录。

## 归档结构

| 目录 | 内容 |
|------|------|
| [`docs/`](docs/README.md) | 学习文档(原理、机制、深度笔记) |
| [`demos/`](demos/README.md) | 可运行的小型实现(解释器、引擎、小工具) |
| [`experiments/`](experiments/README.md) | 动手实验(脚本 + 数据 + 实验记录) |
| [ROADMAP.md](ROADMAP.md) | 选题路线图与候选方向 |

## 学习日志

| 时间 | 轮次 | 主题 | 类型 | 交付物 |
|------|------|------|------|--------|
| 2026-09-06 | R1 | [Git 内部原理](docs/git-internals.md)(对象模型 / refs / packfile,纯 plumbing 命令手工构建提交) | 文档+实验 | ✅ 14 个实验 · [实验记录](experiments/git-internals/README.md) |
| 2026-09-06 | R1 | [Mini 语言解释器 Ripple](demos/mini-interpreter/)(递归下降 + tree-walking,闭包/插值/块级作用域) | Demo | ✅ 25 项测试通过 |
| 2026-09-06 | R1 | [SQLite 索引与查询计划](docs/sqlite-indexing.md)(EXPLAIN QUERY PLAN / 复合索引 / skip-scan) | 文档+实验 | ✅ 11 组实验 · [实验记录](experiments/sqlite-indexing/README.md) |

| 2026-09-06 | R2 | [正则表达式引擎](demos/regex-engine/)(回溯 vs Thompson NFA,ReDoS 实测) | Demo | ✅ 168 项测试 · 双后端 + 与 re 三方一致 |
| 2026-09-06 | R2 | [HTTP/1.1 vs HTTP/2 多路复用与队头阻塞](docs/http-multiplexing.md)(本地双服务器实测 + 帧级证据) | 文档+实验 | ✅ 4 组实验 · [实验记录](experiments/http-multiplexing/README.md) |
| 2026-09-06 | R2 | [Go GMP 调度器](docs/go-gmp-scheduler.md)(源码级:G/M/P 状态机、work-stealing、抢占) | 文档 | ✅ 全论断带 1.24.0 源码行号 · [实验脚本](experiments/go-gmp/)(待装 Go 复跑) |

| 2026-09-06 | R3 | [简易数据库](demos/mini-db/)(WAL + B-tree 存储引擎) | Demo | 🚧 进行中 |
| 2026-09-06 | R3 | [浏览器渲染管线与关键渲染路径](docs/browser-rendering-pipeline.md) | 文档 | 🚧 进行中 |
| 2026-09-06 | R3 | [一致性哈希与分布式路由](demos/consistent-hashing/) | Demo | 🚧 进行中 |

<!-- 新轮次从上方追加新行,交付完成后把 🚧 改为 ✅ -->
