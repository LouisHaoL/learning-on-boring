import { launch } from './lib.mjs';
const BASE = 'http://127.0.0.1:8901';
const browser = await launch();
async function traceMode(v) {
  const page = await browser.newPage();
  const cdpp = await page.context().newCDPSession(page);
  const chunks = [];
  cdpp.on('Tracing.dataCollected', (e) => chunks.push(...e.value));
  const done = new Promise((r) => cdpp.on('Tracing.tracingComplete', r));
  await cdpp.send('Tracing.start', { traceConfig: { includedCategories: ['devtools.timeline'] } });
  await page.goto(`${BASE}/cv-variants.html?v=${v}&n=10000&r=${Math.random()}`, { waitUntil: 'load' });
  await page.waitForTimeout(500);
  await cdpp.send('Tracing.end');
  await done;
  const by = {};
  for (const e of chunks) if (e.ph === 'X' && e.dur) by[e.name] = (by[e.name] || 0) + e.dur;
  const pick = ['ParseHTML', 'EvaluateScript', 'UpdateLayoutTree', 'Layout', 'PrePaint', 'Paint', 'IntersectionObserverController::computeIntersections', 'Layerize', 'HitTest'];
  const out = {};
  for (const k of pick) if (by[k]) out[k] = +(by[k] / 1000).toFixed(1);
  console.log(v || 'none', JSON.stringify(out));
  // trace 明细不落盘,只输出汇总
  await page.close();
}
await traceMode('none');
await traceMode('fixed');
await browser.close();
