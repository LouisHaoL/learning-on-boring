# 自由学习路线图

> 由主 agent 规划方向,子 agent 并发学习,交付物按类归档。
> 分类:`docs/` 学习文档 | `demos/` 可运行 demo | `experiments/` 动手实验记录

## 第 1 轮(2026-09-06,✅ 已完成)

| # | 方向 | 交付物 | 位置 |
|---|------|--------|------|
| 1 | Git 内部原理(objects / refs / packfile) | 文档 + 14 个实验 | `docs/git-internals.md` + `experiments/git-internals/` |
| 2 | Mini 语言解释器 Ripple(递归下降 + tree-walking 求值) | 可运行 demo | `demos/mini-interpreter/` |
| 3 | SQLite 索引与查询计划 | 文档 + 11 组实验 | `docs/sqlite-indexing.md` + `experiments/sqlite-indexing/` |

## 第 2 轮(2026-09-06,进行中)

| # | 方向 | 交付物 | 位置 |
|---|------|--------|------|
| 1 | 正则表达式引擎(Thompson NFA + 回溯对比) | 可运行 demo | `demos/regex-engine/` |
| 2 | HTTP/1.1 vs HTTP/2 多路复用与队头阻塞 | 文档 + 本地实测 | `docs/http-multiplexing.md` + `experiments/http-multiplexing/` |
| 3 | Goroutine 调度器 GMP 模型 | 文档(+可行则实验) | `docs/go-gmp-scheduler.md` |

## 第 3 轮(候选)

- 浏览器渲染管线与关键渲染路径(文档)
- 写一个简易数据库(WAL + B-tree)— demo
- 一致性哈希与分布式路由 — demo
- TCP 拥塞控制演进(文档)

## 第 3 轮(待定)

- LLM Agent 架构模式(tool use / RAG / memory)
- 一致性哈希与分布式路由 — demo
- TCP 拥塞控制演进(文档)
- 写一个简易数据库(WAL + B-tree)— demo

> 每轮完成后在此记录状态,候选方向可随时调整。
