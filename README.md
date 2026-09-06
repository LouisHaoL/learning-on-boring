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

| 2026-09-06 | R3 | [简易数据库](demos/mini-db/)(B+ 树页式存储 + WAL,真实杀进程崩溃恢复) | Demo | ✅ 152 项断言 · 崩溃恢复实验通过 |
| 2026-09-06 | R3 | [浏览器渲染管线与关键渲染路径](docs/browser-rendering-pipeline.md)(headless Chromium 实测:重排/脚本加载/content-visibility) | 文档+实验 | ✅ 4 组 CDP 实验 · [实验记录](experiments/browser-rendering/README.md) |
| 2026-09-06 | R3 | [一致性哈希与分布式路由](demos/consistent-hashing/)(哈希环 + 虚拟节点,迁移率/负载均衡实测) | Demo | ✅ 9 组测试 · 迁移率 9.2% vs 取模 91% |

| 2026-09-06 | R4 | [地图投影的科学、历史与政治](docs/map-projections.md)(高斯绝妙定理、墨卡托、Peters 之争、Web 墨卡托) | 知识研究 | ✅ 350 行 · 数值表全部复算 |
| 2026-09-06 | R4 | [货币简史:从贝壳到法币](docs/history-of-money.md)(货币本质之争、交子、金本位兴衰、三大恶性通胀机制) | 知识研究 | ✅ 406 行 · 多来源交叉核验 |
| 2026-09-06 | R4 | [十二平均律:数学与音乐的四百年](docs/equal-temperament.md)(毕达哥拉斯音差、朱载堉与 Stevin、巴赫澄清) | 知识研究 | ✅ 432 行 · 全数值手算可验证 |

| 2026-09-06 | R5 | [学习科学:什么方法真正有效](docs/science-of-learning.md)(测试效应/间隔/交错证据检验、Dunlosky 十技术评级) | 知识研究 | ✅ 350 行 · 全论断证据分级 |
| 2026-09-06 | R5 | [熵与热力学第二定律:从蒸汽机到信息论](docs/entropy.md)(三层熵同构、麦克斯韦妖 150 年) | 知识研究 | ✅ 353 行 · 证据四级标注 · 手算演算 |
| 2026-09-06 | R5 | [经度问题:大航海时代如何定位自己](docs/longitude-problem.md)(Harrison 航海钟、月距法、波利尼西亚 wayfinding) | 知识研究 | ✅ 354 行 · 一手文献溯源 |

| 2026-09-06 | R6 | [睡眠科学:昼夜节律、记忆巩固与睡眠债务](docs/sleep-science.md)(双过程模型、Walker 争议) | 知识研究 | ✅ 352 行 · 证据分级 + 观察性研究显式标注 |
| 2026-09-06 | R6 | [人类语言谱系:印欧语系假说与语言年代学](docs/indo-european-languages.md)(历史比较法、家乡之争) | 知识研究 | ✅ 352 行 · 一手文献联网核查,含 2025 古 DNA 新证据 |
| 2026-09-06 | R6 | [博弈论改变世界的五个时刻](docs/game-theory-moments.md)(纳什均衡、公地悲剧、拍卖设计) | 知识研究 | ✅ 353 行 · 关键数字逐条核对,六处讹传修正 |

| 2026-09-06 | R7 | R4 三篇提取式自测(回顾位) | 回顾 | ✅ 271 行 · 77% 命中,2 处原文史实勘误回填 |
| 2026-09-06 | R7 | [寒武纪生命大爆发](docs/cambrian-explosion.md)(化石证据、演化速度之争) | 知识研究 | ✅ 351 行 · 关键测年多源核对,假说对阵不站队 |
| 2026-09-06 | R7 | [味觉科学:五味之外](docs/taste-science.md)(鲜味发现史、辣椒与痛觉、超感受者) | 知识研究 | ✅ 355 行 · 转导机制写到分子级,含 oleogustus 误引勘正 |

| 2026-09-06 | R8 | R5 三篇提取式自测(回顾位,盲出题+交错) | 回顾 | ✅ 254 行 · 盲出题+10 轮交错,事实层 83%,3 处勘误回填 |
| 2026-09-06 | R8 | [抗生素发现史与耐药性](docs/antibiotics-history.md)(医学的胜利与透支) | 知识研究 | ✅ 351 行 · Fleming 1945 演讲原文逐字核验,GRAM/GLASS 数据核对 |
| 2026-09-06 | R8 | [历法改革史:时间的社会建构](docs/calendar-reform.md)(儒略→格里高利、消失的十几天) | 知识研究 | ✅ 361 行 · 全部关键算术独立复算,含 Calendar Riot 辨伪 |

| 2026-09-06 | R9 | R6 三篇提取式自测(回顾位,锚定出题) | 回顾 | ✅ 291 行 · 锚定题 73%,❌ 归零,复习日程登记 R12 |
| 2026-09-06 | R9 | [社会性昆虫的集体决策](docs/insect-collective-decision.md)(蜂巢民主、蚁群、无领袖协调) | 知识研究 | ✅ 354 行 · "放大器+刹车"框架,六条可迁移设计原则 |
| 2026-09-06 | R9 | [地震科学:预测为何失败](docs/earthquake-prediction.md)(概率 vs 预报、L'Aquila 审判) | 知识研究 | ✅ 351 行 · Parkfield/L'Aquila 叙事与文献逐条对照纠偏 |

| 2026-09-06 | R10 | R7 两篇提取式自测(回顾位,复用锚清单) | 回顾 | ✅ 317 行 · 锚漂移 23%→8%,4 处勘误回填,登记 R13 复习 |
| 2026-09-06 | R10 | [集装箱如何改变世界](docs/shipping-container.md)(运输成本革命与全球化) | 知识研究 | 🚧 进行中 |
| 2026-09-06 | R10 | [极地探险的决策史:Scott vs Amundsen](docs/polar-expedition-decisions.md)(风险、冗余与运气) | 知识研究 | ✅ 351 行 · 8 决策点对照表,运气 vs 决策定量拆账 |

<!-- 新轮次从上方追加新行,交付完成后把 🚧 改为 ✅ -->
