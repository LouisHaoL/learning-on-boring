// 实验一补充:同样对比,但 2000 个元素 —— 放大布局成本,观察主线程 TaskDuration 差异
// 用法:node exp1b-bigdom.js
import { launch, snapshot, diff, median } from './lib.mjs';
import fs from 'fs';

const BASE = 'http://127.0.0.1:8901';
const results = {};
const browser = await launch();
const page = await browser.newPage();
const cdpp = await page.context().newCDPSession(page);
await cdpp.send('Performance.enable');
for (const mode of ['lefttop', 'transform']) {
  const rows = [];
  for (let i = 0; i < 3; i++) {
    await page.goto(`${BASE}/anim.html?mode=${mode}&n=2000&r=${Math.random()}`, { waitUntil: 'load' });
    await page.waitForTimeout(300);
    const m0 = await snapshot(cdpp);
    await page.waitForTimeout(2000);
    const m1 = await snapshot(cdpp);
    rows.push(diff(m0, m1));
  }
  const med = {};
  for (const k of Object.keys(rows[0])) med[k] = median(rows.map((r) => r[k]));
  results['n2000-' + mode] = rows;
  console.log(`[n2000-${mode}]`, JSON.stringify(med));
}
await browser.close();
fs.writeFileSync('data-exp1b.json', JSON.stringify(results, null, 2));
console.log('written data-exp1b.json');
