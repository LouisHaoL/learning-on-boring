// 公共工具:启动浏览器 + CDP Performance 指标采样
import { chromium } from 'playwright';
import os from 'os';
import path from 'path';

export const CHROME_PATH =
  path.join(os.homedir(), 'AppData', 'Local', 'ms-playwright', 'chromium-1234', 'chrome-win64', 'chrome.exe');

export async function launch() {
  return chromium.launch({ executablePath: CHROME_PATH, headless: true });
}

// CDP Performance.getMetrics 快照,只取我们关心的几项
export async function snapshot(cdpp) {
  const { metrics } = await cdpp.send('Performance.getMetrics');
  const pick = {};
  for (const m of metrics) {
    if (['LayoutCount', 'RecalcStyleCount', 'TaskDuration', 'ScriptDuration', 'LayoutDuration', 'RecalcStyleDuration'].includes(m.name)) {
      pick[m.name] = m.value;
    }
  }
  return pick;
}

export function diff(a, b) {
  const d = {};
  for (const k of Object.keys(a)) d[k] = +(b[k] - a[k]).toFixed(2);
  return d;
}

export const median = (arr) => {
  const s = [...arr].sort((x, y) => x - y);
  const m = Math.floor(s.length / 2);
  return s.length % 2 ? s[m] : +((s[m - 1] + s[m]) / 2).toFixed(2);
};

// 页面内注入:用 rAF 采样帧间隔,统计长帧(>32ms 即掉到 30fps 以下)
export const FRAME_SAMPLER = `
  window.__frames = [];
  let last = performance.now();
  function tick(t) {
    window.__frames.push(+(t - last).toFixed(2));
    last = t;
    requestAnimationFrame(tick);
  }
  requestAnimationFrame(tick);
`;

export function summarizeFrames(frames) {
  if (!frames || frames.length < 2) return null;
  const d = frames.slice(1); // 第一帧是从 0 起算,丢弃
  const long = d.filter((x) => x > 32).length;
  return {
    samples: d.length,
    median_frame_ms: median(d),
    max_frame_ms: Math.max(...d),
    long_frames_gt32ms: long,
  };
}
