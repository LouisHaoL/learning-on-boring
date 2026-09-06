// 实验一:left/top 动画 vs transform 动画 vs JS 布局抖动
// 指标:CDP Performance.getMetrics 差值(2s 采样窗)+ rAF 帧间隔分布
// 用法:node exp1-reflow-vs-transform.js
import { launch, snapshot, diff, FRAME_SAMPLER, summarizeFrames, median } from './lib.mjs';
import fs from 'fs';

const BASE = 'http://127.0.0.1:8901';
const RUNS = 3;
const results = {};

async function runCase(page, cdpp, name, url, settleMs) {
  const rows = [];
  for (let i = 0; i < RUNS; i++) {
    // 每次都用带随机参数的 URL 强制真实导航(hash-only 变更不会重载页面)
    await page.goto(url + (url.includes('?') ? '&' : '?') + 'r=' + Math.random(), { waitUntil: 'load' });
    await page.waitForTimeout(300);
    await page.evaluate(FRAME_SAMPLER).catch(() => {});
    const m0 = await snapshot(cdpp);
    const t0 = Date.now();
    await page.waitForTimeout(settleMs);
    const m1 = await snapshot(cdpp);
    const metrics = diff(m0, m1);
    const frames = await page.evaluate('window.__frames');
    rows.push({ run: i + 1, window_ms: Date.now() - t0, metrics, frames: summarizeFrames(frames) });
  }
  const med = {};
  for (const k of Object.keys(rows[0].metrics)) med[k] = median(rows.map((r) => r.metrics[k]));
  results[name] = { median_metrics: med, runs: rows };
  console.log(`[${name}]`, JSON.stringify(med), '| frames:', JSON.stringify(summarizeFromRuns(rows)));
}

function summarizeFromRuns(rows) {
  const meds = rows.map((r) => (r.frames ? r.frames.median_frame_ms : null));
  const maxs = rows.map((r) => (r.frames ? r.frames.max_frame_ms : null));
  return { median_frame_ms: median(meds.filter((x) => x !== null)), max_frame_ms: median(maxs.filter((x) => x !== null)) };
}

const browser = await launch();
const page = await browser.newPage();
const cdpp = await page.context().newCDPSession(page);
await cdpp.send('Performance.enable');

// 1) CSS 动画:left/top vs transform vs 静止(同页面 ?mode= 切换)
await runCase(page, cdpp, 'css-left-top-n400', BASE + '/anim.html?mode=lefttop&n=400', 2000);
await runCase(page, cdpp, 'css-transform-n400', BASE + '/anim.html?mode=transform&n=400', 2000);
await runCase(page, cdpp, 'css-idle-n400', BASE + '/anim.html?mode=idle&n=400', 2000);

// 2) JS 每帧:布局抖动(写 left + 读 rect) vs 只写 left vs 不动
await runCase(page, cdpp, 'js-thrash-n200', BASE + '/thrash.html?mode=thrash&n=200', 2000);
await runCase(page, cdpp, 'js-clean-write-n200', BASE + '/thrash.html?mode=clean&n=200', 2000);
await runCase(page, cdpp, 'js-idle-n200', BASE + '/thrash.html?mode=idle&n=200', 2000);

await browser.close();
fs.writeFileSync('data-exp1.json', JSON.stringify(results, null, 2));
console.log('written data-exp1.json');
