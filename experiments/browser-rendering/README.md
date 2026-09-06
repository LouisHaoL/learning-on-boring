# 浏览器渲染管线实验

围绕 `docs/browser-rendering-pipeline.md` 中"关键渲染路径 / 重排重绘 / 合成器"的论断做的四组实测。
所有数据来自本机 headless Chromium 151(Playwright 1.63 驱动),2026-09-06。

## 环境

- Windows 10 Pro for Workstations,Node v25.9.0
- 浏览器:Playwright 自带 Chromium 151(`%LOCALAPPDATA%\ms-playwright\chromium-1234`),headless 模式
- 本地 HTTP 服务:`node server.js 8901`(静态页 + 可控延迟脚本 `/slow/<ms>.js`)
- 依赖:`npm install`(仅 playwright,无其他依赖)

## 运行

```bash
node server.js 8901          # 先起服务(另开终端或后台)
node exp1-reflow-vs-transform.js   # left/top vs transform vs JS 布局抖动(400 元素)
node exp1b-bigdom.js               # 同对比放大到 2000 元素
node exp2-script-loading-fcp.js    # sync/defer/async/body末尾 对 FCP/DCL 的影响
node exp3-content-visibility.js    # content-visibility:auto 长列表三视角
node exp4-trace-phases.js          # CDP Tracing 分阶段耗时对比(单次采样)
```

数据输出为同目录 `data-exp*.json`。

## 结果摘要

### 实验一:动画属性与布局抖动(2s 采样窗,CDP `Performance.getMetrics` 差值,3 次中位)

| 场景 | LayoutCount | RecalcStyleCount | TaskDuration |
|---|---|---|---|
| CSS 动画 `left/top`(400 盒子) | **151**(每帧一次) | 151 | 0.45 s |
| CSS 动画 `transform`(同布局) | **0** | 151 | 0.46 s |
| 静止基线 | 0 | 0 | 0.02 s |
| JS 布局抖动:写 left + 读 rect ×200 元素 | **26400** | 26400 | **2.02 s** |
| JS 只写 left 不读(同元素数) | 150 | 150 | 0.23 s |
| 静止基线 | 0 | 0 | 0.02 s |

要点:`transform` 动画每帧仍有 style recalc(动画更新计算样式),但 **LayoutCount=0** ——
布局完全跳过;`left/top` 动画每帧强制完整布局。布局抖动(读-写交错)把 200 个元素的
主线程成本放大到只写不读的 ~9 倍(每帧 200 次强制同步布局 vs 1 次)。

### 实验一 b:放大到 2000 元素(主线程 2s 采样窗,3 次中位)

| 场景 | LayoutCount | LayoutDuration | TaskDuration |
|---|---|---|---|
| `left/top` | 120 | 0.16 s | **2.02 s** |
| `transform` | 0 | 0 | **0.01 s** |

元素变多后布局成本上升,主线程差异放大到 ~200 倍。注意:n=400 时两者 TaskDuration
几乎相同(0.45 vs 0.46)——布局便宜时,`transform` 的收益体现在 paint/合成阶段
(CDP 指标不覆盖),而不是主线程任务耗时;DOM 越复杂差异越明显。

### 实验二:脚本加载方式对 FCP / DOMContentLoaded 的影响(7 次中位,脚本延迟 1200ms)

| 加载方式 | FCP | DCL | 机制 |
|---|---|---|---|
| `<script src>` 在 head | **1236 ms** | 1220.7 ms | 阻塞解析器,后续内容无法解析/绘制 |
| `<script defer src>` 在 head | 28 ms | 1212 ms | 解析不被阻塞;DCL 等 defer 执行完 |
| `<script async src>` 在 head | 28 ms | 9.1 ms | 两边都不等 |
| 同步脚本放 body 末尾 | 28 ms | 1220.6 ms | 前面内容已可绘制;DCL 仍被阻塞 |
| 无脚本 | 28 ms | 9 ms | 基线 |

要点:FCP 差距(1236 vs 28ms)就是"解析阻塞"的直接代价;defer 把"不阻塞解析"和
"执行顺序保证"同时拿到,是 head 脚本的默认选择。DCL 的 1.2s 也解释了为什么
jQuery 时代 `$()` 要包在 DCL 里、且同步脚本会推迟 DCL 里逻辑的执行。

### 实验三:`content-visibility: auto` 与 10000 行长列表

A. 页面内计时:插入 10000 个 `<li>` + 强制同步布局(5 次中位):

| 模式 | insert + layout 总耗时 |
|---|---|
| 无 cv | 139.2 ms |
| cv:auto + contain-intrinsic-size | **39.1 ms**(3.6 倍) |

B. 静态整页加载(fresh tab,5 次中位):DCL 两者相同(13.4 vs 13.8ms,DOM 工作一样);
LayoutDuration 0.123s vs **0.032s**(cv 跳过屏外元素布局);FCP 216 vs 132ms。

C. 一次跳到列表底部(500ms 稳定窗):cv 模式出现 4 次"新进入视口元素的补布局"
(TaskDuration 0.11s),plain 为 0 —— 延迟渲染不是免费的,只是把成本挪到需要时。

D(实验四,CDP Tracing 单次采样,非严格对照):cv 页额外出现
`IntersectionObserverController::computeIntersections` ≈ 60ms(10k 元素的可见性追踪成本)
—— cv:auto 不是纯赚,每帧都要付"判断谁在视口附近"的税。

## 测量注意事项(headless 的坑,复现前必读)

1. **headless 下 paint timing 不可靠**:页面静止后合成器可能不再产帧,
   `first-contentful-paint` 可能根本不记录(none/sync 场景 FCP=null)。
   实验二/三用 CDP `Page.startScreencast` 或单次 `Page.captureScreenshot` 强制出帧解决。
2. **hash-only 导航不重载页面**:`goto('/a.html#x')` 在同一 URL 上是同文档导航,
   页面脚本不会重跑。所有对比页一律用 `?mode=` 查询参数切换状态。
3. **复用同一 tab 反复导航会引入非确定性漂移**:实验三调试期间观察到同一 tab
   第 2 次起导航出现 0.4~1s 的 DCL 漂移(计数器显示不来自 Layout/Style/Script,
   未定位到根因);每次用 fresh tab 后数据稳定。实验三 B/C 部分因此逐 run 新建 tab。
4. **CDP `Performance.getMetrics` 自导航起累计**,窗口对比要取差值;
   但初始渲染发生在 load 事件前后,想看初始布局要直接读绝对值(实验三 B 的做法)。
5. `getBoundingClientRect` 强制的是"布局信息更新";若样式变更只涉及 `transform`,
   Chrome 可以只更新变换不做完整 layout —— 所以布局抖动实验写的是 `left` 而不是 transform。

## 文件

- `server.js` —— 静态服务 + `/slow/<ms>.js` 延迟脚本 + `/fcp?mode=` 页面组装
- `pages/anim.html` —— CSS 动画对比(left/top vs transform vs 静止)
- `pages/thrash.html` —— JS 布局抖动(thrash / clean / idle)
- `pages/longlist.html` / `pages/longlist-bench.html` —— 10000 行列表(加载视角 / 插入计时视角)
- `pages/cv-variants.html` —— cv 变体(无 cv / 固定 intrinsic-size / 整体包裹),供实验四 tracing
- `lib.mjs` —— 浏览器启动、CDP 指标采样、rAF 帧采样公共工具
- `data-exp*.json` —— 原始数据
