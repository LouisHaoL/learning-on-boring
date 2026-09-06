# 自由学习路线图

> 由主 agent 规划方向,子 agent 并发学习,交付物按类归档。
> 分类:`docs/` 学习文档 | `demos/` 可运行 demo | `experiments/` 动手实验记录

## 第 1 轮(2026-09-06,✅ 已完成)

| # | 方向 | 交付物 | 位置 |
|---|------|--------|------|
| 1 | Git 内部原理(objects / refs / packfile) | 文档 + 14 个实验 | `docs/git-internals.md` + `experiments/git-internals/` |
| 2 | Mini 语言解释器 Ripple(递归下降 + tree-walking 求值) | 可运行 demo | `demos/mini-interpreter/` |
| 3 | SQLite 索引与查询计划 | 文档 + 11 组实验 | `docs/sqlite-indexing.md` + `experiments/sqlite-indexing/` |

## 第 2 轮(2026-09-06,✅ 已完成)

| # | 方向 | 交付物 | 位置 |
|---|------|--------|------|
| 1 | 正则表达式引擎(回溯 vs Thompson NFA + ReDoS 实测) | 可运行 demo | `demos/regex-engine/` |
| 2 | HTTP/1.1 vs HTTP/2 多路复用与队头阻塞 | 文档 + 4 组实测 | `docs/http-multiplexing.md` + `experiments/http-multiplexing/` |
| 3 | Go GMP 调度器(源码级,go1.24.0) | 文档 + 待复跑实验脚本 | `docs/go-gmp-scheduler.md` + `experiments/go-gmp/` |

## 第 3 轮(2026-09-06,✅ 已完成)

| # | 方向 | 交付物 | 位置 |
|---|------|--------|------|
| 1 | 简易数据库(B+ 树 + WAL + 真实崩溃恢复) | 可运行 demo | `demos/mini-db/` |
| 2 | 浏览器渲染管线(headless Chromium CDP 实测) | 文档 + 4 组实验 | `docs/browser-rendering-pipeline.md` + `experiments/browser-rendering/` |
| 3 | 一致性哈希(虚拟节点 + FNV-1a 聚簇发现) | 可运行 demo | `demos/consistent-hashing/` |

## 第 4 轮(2026-09-06,进行中)

| # | 方向 | 交付物 | 位置 |
|---|------|--------|------|
| 1 | TCP 拥塞控制(Reno/CUBIC/BBR + 窗口模拟器) | 文档 + Demo | `docs/tcp-congestion-control.md` + `demos/tcp-congestion-sim/` |
| 2 | Ripple 字节码 VM(树遍历 → 字节码/栈式 VM) | 可运行 demo | `demos/ripple-vm/` |
| 3 | Git rebase 与 merge 内部机制 | 文档 + 实验 | `docs/git-rebase-internals.md` + `experiments/git-rebase/` |

## 第 5 轮(候选)

- LSM-tree vs B-tree 写放大(文档 + 实验,衔接 mini-db)
- 浏览器事件循环与微任务/宏任务(文档 + 实验)
- Raft 共识算法(文档 + 可视化 demo)
- 编码:UTF-8/UTF-16/变长整数编码设计(文档 + demo)

## 第 3 轮(待定)

- LLM Agent 架构模式(tool use / RAG / memory)
- 一致性哈希与分布式路由 — demo
- TCP 拥塞控制演进(文档)
- 写一个简易数据库(WAL + B-tree)— demo

> 每轮完成后在此记录状态,候选方向可随时调整。
