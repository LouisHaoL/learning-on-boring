// 实验二:同步 / defer / async / body 末尾脚本对 FCP 与 DOMContentLoaded 的影响
// 脚本统一延迟 1200ms 返回,排除"脚本内容本身耗时"的干扰,只看加载位置/方式的差异。
// 用法:node exp2-script-loading-fcp.js
import { launch, median } from './lib.mjs';
import fs from 'fs';

const BASE = 'http://127.0.0.1:8901';
const RUNS = 7;
const modes = ['sync', 'defer', 'async', 'bottom', 'none'];
const results = {};

const browser = await launch();
const page = await browser.newPage();
const cdpp = await page.context().newCDPSession(page);
// headless/后台窗口在页面静止后不再产帧,paint timing 可能永远不记录;
// 用 CDP screencast 强制合成器持续产帧,保证 FCP 被如实上报。
await cdpp.send('Page.startScreencast', { format: 'jpeg', quality: 10, everyNthFrame: 1 });
cdpp.on('Page.screencastFrame', (e) => cdpp.send('Page.screencastFrameAck', { sessionId: e.sessionId }).catch(() => {}));

for (const mode of modes) {
  const rows = [];
  for (let i = 0; i < RUNS; i++) {
    await page.goto(`${BASE}/fcp?mode=${mode}&r=${Math.random()}`, { waitUntil: 'load' });
    await page.waitForTimeout(1000); // 给首个内容帧留出呈现时间(见 README 的测量注意)
    const m = await page.evaluate(() => {
      const fcpEntry = performance.getEntriesByName('first-contentful-paint')[0];
      const nav = performance.getEntriesByType('navigation')[0];
      return {
        fcp: fcpEntry ? +fcpEntry.startTime.toFixed(1) : null,
        dcl: +nav.domContentLoadedEventStart.toFixed(1),
        loadEvent: +nav.loadEventStart.toFixed(1),
        slowScriptDone: window.__slowDone !== undefined,
      };
    });
    rows.push(m);
  }
  results[mode] = rows;
  console.log(`[${mode}] FCP median = ${median(rows.map((r) => r.fcp))} ms | DCL median = ${median(rows.map((r) => r.dcl))} ms`);
}

await browser.close();
fs.writeFileSync('data-exp2.json', JSON.stringify(results, null, 2));
console.log('written data-exp2.json');
