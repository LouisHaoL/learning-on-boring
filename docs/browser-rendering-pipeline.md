# 浏览器渲染管线与关键渲染路径

> 本文的耗时/计数数据均来自本机真实实验(headless Chromium 151 / Playwright,2026-09-06),
> 脚本与原始数据见 `experiments/browser-rendering/`(README 里有运行方式与逐表数据)。
> 文中区分【实测】与【文档知识】:标"实测"的论断有对应实验可复跑;
> 标"文档知识"的来自 HTML Standard、CSS 规范、web.dev 与 Chromium 设计文档,
> 文末附来源清单。实验覆盖不到的细节一律标注来源,不做编造。

## 0. 一句话总结

浏览器把"从字节到像素"拆成一条单向流水线:HTML→DOM、CSS→CSSOM、两者合成渲染树、
算布局(Layout)、光栅化(Paint/Raster)、最后合成(Composite)显示。
这条流水线的每一级都有不同的重算成本:改 `transform`/`opacity` 只走最后一级(合成器线程,主线程可空闲);
改几何属性(`left`/`width`)要重走 Layout 以下所有级;JS 里"写样式后立刻读几何"还会把
布局提前拆成一帧里几十次同步执行(布局抖动)。理解"改了什么 → 需要重跑哪几级",
就是前端渲染性能优化的全部底层逻辑。

---

## 1. 管线总览

### 1.1 从字节到像素【文档知识】

```
 网络字节流
    │  (字节→字符→token→节点,见 §2)
    ▼
 ┌─────────┐   ┌──────────┐
 │   DOM   │   │  CSSOM   │◄── *.css 文本
 └────┬────┘   └────┬─────┘
      │             │
      └──┬──────────┘
         ▼
   Style / Render Tree          ← 每个可见节点的"计算样式"
         │                        (display:none 的节点不进渲染树)
         ▼
   Layout(重排 / reflow)     ← 精确位置与大小(几何信息)
         │
         ▼
   PrePaint / Paint            ← 绘制指令列表(paint ops),
         │                        按合成层分组;光栅化到位图可并行
         ▼
   Composite(合成)           ← 把各层位图按正确顺序叠成最终一帧,
                                   在合成器线程/GPU 上完成
         ▼
      屏幕像素
```

关键性质:**流水线是增量的**。浏览器会标记"脏"的部分,只重算从失效点开始往下的各级:
改颜色 → 跳过 Layout 只重 Paint;改 `transform` → 连 Paint 都可跳过只重 Composite;
改字号 → 全部重来【文档知识,web.dev "Render-perf" / Chromium Life of a Pixel】。
"改什么决定重跑几级"就是下文 §3、§4 的全部内容。

### 1.2 渲染树里有什么、没有什么【文档知识】

"合成 Render Tree"这一步(Chromium 里称 style/update-tree 构建阶段)的规则:

- `display: none` 的子树**不进入**布局与绘制——但它仍在 DOM 里,JS 可访问;
- `visibility: hidden` 的元素**在**渲染树中(占布局空间),只是不画出来;
- `head`、`<script>`、`meta` 等非视觉节点不参与;
- 伪元素(`::before` 等)在这一步才"凭空"进入渲染树——它们不在 DOM 里。

这条规则解释了两个常见现象:用 `display: none` 隐藏大块内容后修改其内部样式
不会触发重排(它不在布局树里);而切换 `display: none → block` 是全子树布局,
比切 `visibility` 贵得多。

### 1.2 渲染进程里的线程分工【文档知识】

Chromium 中每个站点隔离的渲染进程内至少有三类线程(Chromium 设计文档
"Life of a Pixel" / "Rendering Architecture"):

```
 渲染进程
 ┌──────────────────────────────────────────────┐
 │ 主线程 Main thread                            │
 │   DOM 解析/JS 执行/样式/布局/paint 指令记录     │
 ├──────────────────────────────────────────────┤
 │ 合成器线程 Compositor thread                  │
 │   接收滚动/合成层动画指令、维护层树、发起 commit │
 ├──────────────────────────────────────────────┤
 │ 光栅线程池 Raster threads                     │
 │   把 paint 指令真正画成位图(Skia),可多核并行   │
 └──────────────────────────────────────────────┘
        │ 层位图(纹理)
        ▼
 GPU 进程(viz / Display Compositor):把各渲染进程的纹理
 最终合成到屏幕窗口
```

这个分工是 §4、§5 两个结论的物理基础:
`transform`/`opacity` 动画之所以不卡主线程(§4.2),以及滚动/输入之所以能被
合成器线程"先斩后奏"(§5.3)。

---

## 2. 解析:增量、脚本阻塞与预加载扫描器

### 2.1 增量解析:边收边建 DOM【文档知识】

HTML 解析器不是"下载完再解析",而是**网络来一段解析一段**(HTML Standard
把解析器实现为逐 token 的状态机,分块喂入)。实测佐证:实验二所有页面在
FCP ≈ 28ms 时脚本还在路上(1200ms 后才返回),说明首屏文本在文档尚未接收完成时
就已解析并绘制——解析与网络是流水线关系,不是串行。

但这条流水线有三类"刹车":

### 2.2 脚本对解析的三种阻塞方式【实测 + 文档知识】

HTML 规范(Standard §4.12.1)规定:同步 `<script src>` 必须在**继续解析之前**
下载并执行完毕——因为脚本可能 `document.write` 改变后面的字节流。
`defer`/`async` 则解除这种依赖:

```
                 下载          执行          DCL
 同步(head)      ████          ██    ……解析停摆……  等它
 defer(head)     ████(并行)          ██   解析不停    等它
 async(head)     ████(并行)      ██(谁先到谁执行)   不等
```

实验二实测(脚本统一延迟 1200ms 返回,7 次中位):

| 加载方式 | FCP | DOMContentLoaded | 机制 |
|---|---|---|---|
| 同步脚本在 head | **1236 ms** | 1220.7 ms | 解析器停在 head,首屏内容根本没被解析 |
| `defer` 在 head | 28 ms | 1212 ms | 解析不被阻塞;但 DCL 事件等 defer 执行完 |
| `async` 在 head | 28 ms | 9.1 ms | 下载、执行、DCL 全不等 |
| 同步脚本放 body 末尾 | 28 ms | 1220.6 ms | 前面的内容已可解析绘制;DCL 仍被它拖住 |
| 无脚本基线 | 28 ms | 9 ms | — |

两个读法:
- FCP 1236 vs 28ms 就是"解析阻塞"的直接代价——**脚本位置决定用户等多久看到首屏**;
- `defer` 拿到了"不阻塞解析"但保住了"按序执行 + DCL 前执行"的语义,所以是
  需要操作 DOM 的脚本的默认正确答案;`async` 适合独立统计类脚本;
  `type="module"` 默认行为等同 `defer`(文档知识,Standard §4.12.1)。

### 2.3 预加载扫描器(preload scanner)【文档知识】

解析器被同步脚本卡住时,**另一个轻量扫描器会继续扫剩余字节流**,提前发现
`<img>`/CSS/后续脚本的 URL 并发请求(web.dev Learn Performance;Chromium 源码中的
`HTMLPreloadScanner`)。这就是为什么同步脚本阻塞的是"解析和执行",
而不完全是"网络"——实验二里 defer 脚本(在解析器可继续扫到的 head 内)也确实
在 1200ms 后立即执行、DCL 才 1212ms 而不是 1200ms+解析耗时。预加载扫描器救的是
网络瀑布,救不了解析器——同步脚本的执行前解析器必须停,这是规范规定,也是
实验二 FCP 差 1.2s 的原因。

### 2.4 CSS 是渲染阻塞的:CSSOM 不全,首帧不算【文档知识】

HTML 解析不等待 CSS(CSS 不阻塞 DOM 解析——`DOMContentLoaded` 的解析部分),
但**等待 CSSOM 构建完成才能算样式、才能渲染首帧**:任何元素的计算样式都可能是
"后面的样式表"改变的,所以在样式表到达并解析完之前,浏览器绘制的是
"白屏 + 已解析的 DOM"而不是首屏内容(渲染阻塞,render-blocking;
web.dev "Optimize CSS")。这也是 Critical CSS 手法的依据:把首屏必需的规则
内联进 HTML,外链大样式表让它异步加载,消除"HTML 到了、CSS 还在路上"的白屏窗口。

一个由此衍生的优先级规则【文档知识】:同步脚本若排在 `<link rel=stylesheet>`
之后,必须先等 CSS 下载完——因为脚本可能读取元素的计算样式
(`getComputedStyle`),浏览器要保证它读到 CSS 应用后的值。所以
"CSS in head + 同步 script"会串行成 CSS→script→解析,这是瀑布图上最常见的
白屏拉长模式。

---

## 3. Layout(重排)与 Paint(重绘)

### 3.1 什么触发重排 / 重绘【文档知识】

| 你改的东西 | Style | Layout | Paint | Composite |
|---|---|---|---|---|
| `color`/`background`/`visibility` | ✓ | — | ✓ | ✓ |
| `width`/`height`/`left`/`top`/`font-size` | ✓ | ✓ | ✓ | ✓ |
| `transform` / `opacity`(动画态) | ✓ | — | —(见 §4.2) | ✓ |
| DOM 增删 | ✓ | ✓ | ✓ | ✓ |

"重排/重绘"的官方机制名就是 Layout / Paint 两级失效与重算。
实验一对第一列之外的全部三种都做了计数实测(CDP `Performance.getMetrics`,
2s 采样窗,400 个盒子):

| 场景 | LayoutCount | RecalcStyleCount | 主线程 TaskDuration |
|---|---|---|---|
| CSS 动画 `left/top` | **151**(每帧 1 次) | 151 | 0.45 s |
| CSS 动画 `transform` | **0** | 151 | 0.46 s |
| 静止基线 | 0 | 0 | 0.02 s |

注意细节:`transform` 动画每帧**仍有 style recalc**(动画驱动的是计算样式更新),
但 LayoutCount 为 0——几何布局整级跳过。这也是反驳"transform 动画零主线程成本"
的说法时常用的精确表述:省掉的是 Layout 与 Paint,不是全部主线程工作。

### 3.2 强制同步布局与布局抖动(layout thrashing)【实测】

主线程本来把布局**批处理**到每帧一次:rAF 里随便写样式,布局推迟到该帧渲染阶段统一做。
但 JS 在"写之后立刻读几何"(读 `offsetTop`/`getBoundingClientRect` 等)时,
浏览器为保证读到新值,必须**当场把布局跑完**——这就是强制同步布局
(forced synchronous layout,web.dev "Avoid large, complex layouts...")。

一帧内循环"写→读"多次,就是布局抖动。实测(200 个元素,2s 窗):

| 场景 | LayoutCount | 主线程 TaskDuration |
|---|---|---|
| JS 抖动:写 `left` → 立刻读 rect ×200/帧 | **26400** | **2.02 s** |
| JS 只写 `left` 不读(同帧合并为 1 次布局) | 150 | 0.23 s |
| 静止基线 | 0 | 0.02 s |

只写不读时,浏览器把 200 次写合并成每帧 1 次布局(150 ≈ 帧数);交错读写后,
布局被拆成每帧 200 次同步执行,主线程成本 ~9 倍。修复思路即"先读后写"
(batch reads, then writes)或用 FastDOM 之类的读写分批库【文档知识】。

一个容易踩的坑(实验过程中真实发生):如果"写"的是 `transform`,
读 `getBoundingClientRect` **不**触发完整布局——变换不影响布局几何,
Chrome 只需更新变换即可回答。所以布局抖动实验必须写 `left` 这类真几何属性才能复现
(见 experiments README"测量注意事项"第 5 条)。

### 3.3 布局成本随 DOM 规模放大【实测】

同样一对动画,元素数从 400 加到 2000(exp1b,2s 窗,3 次中位):

| 场景 | LayoutCount | LayoutDuration | 主线程 TaskDuration |
|---|---|---|---|
| `left/top` | 120 | 0.16 s | **2.02 s** |
| `transform` | 0 | 0 | **0.01 s** |

400 个盒子时两者主线程耗时几乎一样(0.45 vs 0.46s)——布局便宜时,`transform`
的收益主要在 paint/合成侧(CDP 计数器不覆盖);DOM 一大,差距立刻变成 200 倍。
**"为什么 transform 动画不卡主线程"的完整答案**:① 它不改几何,布局整级跳过
(LayoutCount=0 实测);② 它不改绘制指令内容,Paint 也可跳过(web.dev
"Stick to compositor-only properties");③ 动画本身由合成器线程按曲线插值,
主线程只负责启动它,之后即使主线程忙 500ms,动画照常走——这正是 §5.3 的推论。

---

## 4. 分层与合成

### 4.1 为什么需要合成层【文档知识】

如果整页是一张位图,那么任何像素变化(哪怕一个光标闪烁)都要整页重画。
合成器把页面切成若干**层**(有 `will-change`/`transform` 动画/视频/canvas 等的元素
会被提升为独立层,Chromium 按启发式决定),每层独立光栅化为纹理
(光栅线程池并行做),合成时只需对纹理做变换+叠加(GPU 三角形绘制)。
滚动就变成了"把整层纹理往上平移"——这就是滚动流畅的结构性原因。

层的代价是内存与合成时间(每层都要光栅化、占显存),所以优化指南说
"stick to compositor-only properties **and manage layer count**",
`will-change` 不是越多越好【文档知识,web.dev 同名文章】。

### 4.2 动画的正确层级:交出去 vs 留在主线程【文档知识】

- **可合成动画**(`transform`/`opacity`):主线程把动画交给合成器线程,
  之后每帧由合成器/GPU 独立产出。主线程可长任务不阻塞动画。
- **不可合成动画**(`left`/`margin`/`width`/`:hover` 改色…):每帧都在主线程走
  style→layout→paint。主线程一忙,帧就丢。

实测对应:§3.1 表格里 `left/top` 的 LayoutCount=151(60+Hz 帧率下每帧都布局),
`transform` 为 0;§3.3 里 2000 元素下主线程 2.02s vs 0.01s。

---

## 5. 帧生命周期与输入

### 5.1 一帧内主线程发生什么【文档知识】

HTML Standard 定义的事件循环"渲染机会"(rendering opportunity)步骤:

```
 一帧(60Hz ≈ 16.7ms 预算)
 ─────────────────────────────────────────────────────────► t
 │输入事件派发│rAF 回调│Style│Layout│PrePaint│Paint│→ commit → 合成器线程
 └──────────┴────────┴─────┴──────┴────────┴─────┘
   resize/scroll/   JS      重排    绘制指令    交给合成器
   pointermove 等   (动画、
                     数据更新)
```

- **rAF 回调**在样式计算**之前**执行:回调里写的样式会在同一帧生效,
  不会"白写后等下一帧"。这也是测帧间隔用 rAF 采样的原因(experiments/lib.mjs)。
- 帧是否产生由浏览器决定:页面不可见/无更新时可以不出帧(headless 实验里
  paint timing 依赖强制出帧的原因,见 experiments README 注意事项 1)。
- 帧率由显示器 vsync 驱动,主线程超预算(>16.7ms)就掉帧;>50ms 的主线程任务
  被定义为 Long Task(Long Tasks API)【文档知识】。

一帧的实测节奏【实测,顺带说明 headless 的测量环境】:实验一对所有场景用
页面内 rAF 采样了帧间隔,各场景(含重排繁重的 left/top 动画)中位帧间隔均为
**13.3ms、无 >32ms 长帧**——这不是"重排不卡",而是实验环境没有真实显示器,
headless 的 BeginFrame 节奏由浏览器自定(≈75Hz),且 400 个小盒子的布局成本
远小于帧预算。这正是本文用 **LayoutCount/TaskDuration 计数器**而不是帧率做主指标
的原因:微基准里帧率对主线程负载不敏感,计数器才能如实反映管线各级的工作量
(原始帧数据在 data-exp1.json 各 run 的 frames 字段)。

### 5.2 Long Task 与 INP 的机制联系【文档知识】

INP(Interaction to Next Paint,web.dev,2024 起 Core Web Vitals)衡量
"用户输入到下一帧视觉反馈"的延迟,良好阈值 200ms。机制上,
输入事件派发排在帧首:如果输入到达时主线程正在跑一个 800ms 的长任务,
这个输入的回调要排队等它跑完,再等 style/layout/paint 完成——INP 直接被拉爆。
所以"拆长任务"(`setTimeout` 切片、`scheduler.yield()`)本质是给输入回调
留出插队空隙。这与 §3 的结论同源:**主线程队列里堆的是什么,
决定的是动画帧率还是交互延迟**。

### 5.3 为什么滚动/输入可以被合成器线程处理【文档知识】

滚动默认不改 DOM:只是合成层纹理的平移。因此 Chromium 把滚轮/触摸手势先派给
**合成器线程**:它能直接更新 scroll offset 并立刻产出新帧,主线程哪怕在跑
10 秒的 JS,页面照样能滚(compositor-driven scroll,Chromium 设计文档)。
两个例外会把滚动"钉回"主线程:
- **非快速可滚动区域**:页面上任何注册了 wheel/touch 监听的区域
  (`addEventListener('wheel', …)`,哪怕空函数)——因为监听器可能 `preventDefault`,
  合成器不敢先滚,必须等主线程裁决;
- 滚动驱动的样式/布局效果(backdrop-filter、粘性定位的复杂情况等)。

由此也解释 §4 的现象的统一本质:**合成器线程独立做决定所需的全部信息,
如果都已在 commit 时交给它,主线程就只是"旁观者"。**

---

## 6. 常见优化手段的机制依据

| 手段 | 针对的管线阶段 | 机制一句话 |
|---|---|---|
| Critical CSS(内联首屏样式) | CSSOM 阻塞渲染 | CSS 是渲染阻塞的(CSSOM 不全无法算样式);外链 CSS 未到 = 首屏样式算不了。内联关键部分消除这个往返【文档知识,web.dev "Optimize CSS"】 |
| `font-display: swap/optional` | Paint 前 | 字体下载期间按策略先用后备字体绘制(block 期默认最长 ~3s,swap 期无限后备交换),避免"看不见的文字"(FOIT)【文档知识,CSS Fonts 4 §font-display】 |
| `content-visibility: auto` | Style/Layout/Paint 全级 | 屏外元素整棵子树跳过渲染,用 `contain-intrinsic-size` 占位估计尺寸【实测,见下】 |
| defer/module 脚本 | 解析阻塞 | §2.2 实测:FCP 1236→28ms |
| 拆长任务 | §5.2 | 输入回调能插队,INP 才有机会 <200ms |
| 读写分离 / FastDOM | Layout | §3.2:26400 次/2s 布局 → 150 次 |

### 6.1 content-visibility: auto 实测【实测】

10000 行列表,三种视角(exp3,5 次中位):

| 视角 | 无 cv | cv:auto | 说明 |
|---|---|---|---|
| JS 插入 10000 节点 + 强制同步布局 | 139.2 ms | **39.1 ms** | 屏外子树布局整棵跳过 |
| 静态页加载 LayoutDuration(CDP) | 0.123 s | **0.032 s** | 同上,导航场景 |
| 静态页 DCL | 13.4 ms | 13.8 ms | DOM 工作相同,DCL 与渲染无关——它本来就是解析事件 |
| 一次跳到列表底部后的补布局 | 0 | 4 次(0.11s) | 延迟渲染把成本挪到"真正要显示时" |
| Tracing:可见性追踪成本 | — | computeIntersections ≈ 60ms | cv 不是纯赚,每帧要判断"谁在视口附近" |

结论:`content-visibility: auto` 的收益来自**跳过屏外渲染**(前两行),
代价是**滚动时的补渲染**和**常驻的可见性追踪**;它改变的是成本发生的时间与总量,
不消除成本。这也是它适合长列表/长文章、不适合整页滥用的原因(官方指南同)。

### 6.2 一个反面教材:优化要选对属性

实验二里"同步脚本放 body 末尾"FCP 只有 28ms(与无脚本相同)但 DCL 1220ms——
同样的脚本,挪个位置,用户感知(FCP)与页面可用性(DCL 之后绑定的逻辑)
就分开了。渲染优化的第一问永远是:**这个资源/变更卡的是管线的哪一级**。

---

## 7. 实验索引与来源

### 实验(experiments/browser-rendering/)

| 实验 | 覆盖本文小节 |
|---|---|
| exp1 / exp1b:动画属性 vs 布局抖动(400/2000 元素) | §3.1 §3.2 §3.3 §4.2 |
| exp2:sync/defer/async/bottom 脚本 FCP/DCL | §2.1 §2.2 |
| exp3:content-visibility 三视角 | §6.1 |
| exp4:CDP Tracing 分阶段耗时(Layout/PrePaint/computeIntersections) | §3 §6.1 |

headless 测量的坑(paint timing 需强制出帧、hash 导航不重载、tab 复用漂移)
见该目录 README"测量注意事项"——其中第 3 条(0.4~1s DCL 漂移)未能定位根因,
已如实记录。

### 主要来源【文档知识】

- HTML Standard §4.12.1(script 元素:async/defer/执行语义)、事件循环与渲染步骤(§8.1.7)
- CSS Fonts Module Level 4,§font-display(block/swap/optional 周期)
- web.dev(Learn Performance / 渲染性能系列):
  "Rendering Performance"、"Stick to compositor-only properties and manage layer count"、
  "Avoid large, complex layouts and layout thrashing"、"Optimize CSS"、"Optimize INP"、
  "content-visibility"、"Preload scanner"(Learn Performance — Parse HTML? 网络/解析章节)
- Chromium 设计文档与公开分享:"Life of a Pixel"(渲染管线各级与线程分工)、
  "Rendering Architecture"(合成器线程、compositor-driven scroll、
  non-fast-scrollable region)
- Long Tasks API 与 INP 阈值:web.dev/articles/optimize-inp(良好 ≤200ms)、
  w3c/longtasks 说明(>50ms)
