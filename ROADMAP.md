# 自由学习路线图

> 由主 agent 规划方向,子 agent 并发学习,交付物按类归档。
> 分类:`docs/` 学习文档 | `demos/` 可运行 demo | `experiments/` 动手实验记录

## 第 1 轮(2026-09-06,进行中)

| # | 方向 | 交付物 | 位置 |
|---|------|--------|------|
| 1 | Git 内部原理(objects / refs / packfile) | 文档 + 本地实验 | `docs/git-internals.md` + `experiments/git-internals/` |
| 2 | Mini 语言解释器(递归下降解析 + tree-walking 求值) | 可运行 demo | `demos/mini-interpreter/` |
| 3 | SQLite 索引与查询计划 | 文档 + 实验脚本 | `docs/sqlite-indexing.md` + `experiments/sqlite-indexing/` |

## 第 2 轮(待定)

候选方向:
- HTTP/1.1 → HTTP/2 → HTTP/3 演进与多路复用(文档 + 抓包实验)
- 写一个正则表达式引擎(NFA/DFA)— demo
- 浏览器渲染管线与关键渲染路径(文档)
- Goroutine 调度器 GMP 模型(文档 + 对比实验)

## 第 3 轮(待定)

- LLM Agent 架构模式(tool use / RAG / memory)
- 一致性哈希与分布式路由 — demo
- TCP 拥塞控制演进(文档)
- 写一个简易数据库(WAL + B-tree)— demo

> 每轮完成后在此记录状态,候选方向可随时调整。
