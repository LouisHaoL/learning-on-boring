// 实验三:content-visibility: auto 对 10000 行长列表渲染成本的影响
// 三个视角:
//  A. 页面内计时:插入 10000 节点 + 强制同步布局的总耗时(insert+style+layout)
//  B. 导航加载:FCP / DCL + 自导航起累计的 CDP 布局与任务耗时(绝对值)
//  C. 滚动代价:一次性跳到列表底部后,稳定窗口内的布局/任务增量
// 用法:node exp3-content-visibility.js
import { launch, snapshot, diff, median } from './lib.mjs';
import fs from 'fs';

const BASE = 'http://127.0.0.1:8901';
const RUNS = 5;
const results = {};

const browser = await launch();
const page = await browser.newPage();
const cdpp = await page.context().newCDPSession(page);
await cdpp.send('Performance.enable');
// 与实验二同理:强制合成器产帧,保证 FCP 被记录
await cdpp.send('Page.startScreencast', { format: 'jpeg', quality: 10, everyNthFrame: 1 });
cdpp.on('Page.screencastFrame', (e) => cdpp.send('Page.screencastFrameAck', { sessionId: e.sessionId }).catch(() => {}));

// ---- A. 插入 + 强制布局计时 ----
for (const mode of ['plain', 'cv']) {
  const rows = [];
  for (let i = 0; i < RUNS; i++) {
    await page.goto(`${BASE}/longlist-bench.html?mode=${mode}&n=10000&r=${Math.random()}`, { waitUntil: 'load' });
    rows.push(await page.evaluate('window.__bench'));
  }
  results['A_insert_' + mode] = rows;
  console.log(`[A insert+layout ${mode}] ${median(rows.map((r) => r.insert_and_layout_ms))} ms`);
}

// ---- B. 导航加载:静态整页(每次 fresh tab —— 复用同一 tab 时出现过非确定性
//      0.4~1s 的 DCL 漂移,见 README"测量注意") ----
for (const mode of ['plain', 'cv']) {
  const rows = [];
  for (let i = 0; i < RUNS; i++) {
    const p = await browser.newPage();
    const c = await p.context().newCDPSession(p);
    await c.send('Performance.enable');
    await p.goto(`${BASE}/longlist.html?mode=${mode}&r=${Math.random()}`, { waitUntil: 'load' });
    // 单次截图强迫合成器出一帧,保证 FCP 被记录(不做持续 screencast,避免干扰 DCL)
    await c.send('Page.captureScreenshot', { format: 'jpeg', quality: 10 }).catch(() => {});
    await p.waitForTimeout(200);
    const nav = await p.evaluate(() => {
      const fcp = performance.getEntriesByName('first-contentful-paint')[0];
      const n = performance.getEntriesByType('navigation')[0];
      return { fcp: fcp ? +fcp.startTime.toFixed(1) : null, dcl: +n.domContentLoadedEventStart.toFixed(1) };
    });
    const m = await snapshot(c); // 绝对值 = 自导航起累计
    rows.push({ ...nav, LayoutCount: m.LayoutCount, LayoutDuration: m.LayoutDuration, RecalcStyleDuration: m.RecalcStyleDuration, TaskDuration: m.TaskDuration });
    await p.close();
  }
  results['B_load_' + mode] = rows;
  const med = {};
  for (const k of ['fcp', 'dcl', 'LayoutCount', 'LayoutDuration', 'RecalcStyleDuration', 'TaskDuration']) med[k] = median(rows.map((r) => r[k]));
  results['B_load_' + mode + '_median'] = med;
  console.log(`[B load ${mode}]`, JSON.stringify(med));
}

// ---- C. 滚动到底部:稳定后窗口内的增量(跳过渲染的元素首次进入视口才布局) ----
for (const mode of ['plain', 'cv']) {
  const rows = [];
  for (let i = 0; i < RUNS; i++) {
    const p = await browser.newPage();
    const cs = await p.context().newCDPSession(p);
    await cs.send('Performance.enable');
    await p.goto(`${BASE}/longlist.html?mode=${mode}&r=${Math.random()}`, { waitUntil: 'load' });
    await p.waitForTimeout(500);
    const m0 = await snapshot(cs);
    await p.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
    await p.waitForTimeout(500);
    const m1 = await snapshot(cs);
    rows.push(diff(m0, m1));
    await p.close();
  }
  const med = {};
  for (const k of Object.keys(rows[0])) med[k] = median(rows.map((r) => r[k]));
  results['C_scroll_' + mode] = { median: med, runs: rows };
  console.log(`[C scroll-to-bottom ${mode}]`, JSON.stringify(med));
}

await cdpp.send('Page.stopScreencast').catch(() => {});
await browser.close();
fs.writeFileSync('data-exp3.json', JSON.stringify(results, null, 2));
console.log('written data-exp3.json');
