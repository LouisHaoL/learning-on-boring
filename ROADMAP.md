# 自由学习路线图

> 由主 agent 规划方向,子 agent 并发学习,交付物按类归档。
> 分类:`docs/` 学习文档 | `demos/` 可运行 demo | `experiments/` 动手实验记录

## 方法论(2026-09-06 用户明确)

**选题约束**:计算机/编程相关主题一律不选(见 R4 转向说明)。
**研究手段全开放**,按课题特点选用,不设限:
- 搜索溯源(一手资料、原始文献、多方对比)
- 数学推导与演算
- 思想实验、假设-检验
- 轻量小实验(计算器、公开数据集、纸笔演算、日常观察)——**不是**工程项目
- 自学方法本身也是合法课题(学习科学、元认知)

每个 agent 拿到课题后应先判断:这个问题靠什么手段最能推进?然后在交付物里
说明用了哪些手段、各自贡献了什么(可写进文档开头的方法论一节)。

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

## 第 4 轮(2026-09-06,✅ 已完成,转向纯知识领域的首轮)

> 课题方向约束:计算机/编程相关主题一律不选(用户明确要求)。R1-R3 的
> 技术类交付保留归档,后续轮次聚焦通识知识。

| # | 方向 | 交付物 | 位置 |
|---|------|--------|------|
| 1 | 地图投影的科学、历史与政治(高斯绝妙定理、Peters 之争、Web 墨卡托) | 知识研究文档 | `docs/map-projections.md` |
| 2 | 货币简史:从贝壳到法币(货币本质、金本位、恶性通胀机制) | 知识研究文档 | `docs/history-of-money.md` |
| 3 | 十二平均律:数学与音乐的四百年(音差定理、朱载堉、巴赫澄清) | 知识研究文档 | `docs/equal-temperament.md` |

## 第 5 轮(2026-09-06,进行中)

| # | 方向 | 交付物 | 位置 |
|---|------|--------|------|
| 1 | 学习科学:间隔重复/测试效应/交错练习的证据检验 | 知识研究文档 | `docs/science-of-learning.md` |
| 2 | 熵与热力学第二定律:从蒸汽机到信息论 | 知识研究文档 | `docs/entropy.md` |
| 3 | 经度问题:大航海时代如何定位自己(衔接 R4 地图投影) | 知识研究文档 | `docs/longitude-problem.md` |

## 第 3 轮(待定)

- LLM Agent 架构模式(tool use / RAG / memory)
- 一致性哈希与分布式路由 — demo
- TCP 拥塞控制演进(文档)
- 写一个简易数据库(WAL + B-tree)— demo

> 每轮完成后在此记录状态,候选方向可随时调整。
