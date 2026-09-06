// 极简本地 HTTP 服务:静态文件 + 可控延迟脚本(用于实验二)
// 用法:node server.js  [port=8901]
import http from 'http';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const root = path.dirname(fileURLToPath(import.meta.url));
const port = Number(process.argv[2] || 8901);

const server = http.createServer((req, res) => {
  const u = new URL(req.url, 'http://localhost');
  // /slow/<ms>.js —— 延迟 <ms> 毫秒后返回一段普通 JS
  const slow = u.pathname.match(/^\/slow\/(\d+)\.js$/);
  if (slow) {
    const ms = Number(slow[1]);
    setTimeout(() => {
      res.writeHead(200, { 'Content-Type': 'application/javascript' });
      res.end('window.__slowDone = performance.now();');
    }, ms);
    return;
  }
  // /fcp?mode=sync|defer|async|bottom|none —— 组装脚本加载方式对比页(实验二)
  // sync 脚本放 <head>(阻塞所有后续内容的解析);bottom 放正文末尾作对照
  if (u.pathname === '/fcp') {
    const mode = u.searchParams.get('mode') || 'sync';
    const slow = '/slow/1200.js';
    const S = `<script src="${slow}"></` + 'script>';
    const head = { sync: S, defer: `<script defer src="${slow}"></` + 'script>', async: `<script async src="${slow}"></` + 'script>' };
    const slots = {
      sync:   { head: head.sync, body: '' },
      defer:  { head: head.defer, body: '' },
      async:  { head: head.async, body: '' },
      bottom: { head: '', body: S },
      none:   { head: '', body: '' },
    };
    const sl = slots[mode] ?? slots.none;
    const tpl = fs.readFileSync(path.join(root, 'pages', 'script-fcp.html'), 'utf8');
    const html = tpl.replace('HEAD_SLOT', sl.head).replace('BODY_SLOT', sl.body);
    res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
    res.end(html);
    return;
  }
  let p = u.pathname === '/' ? '/index.html' : u.pathname;
  p = p.replaceAll('..', ''); // 简单防目录穿越
  const file = path.join(root, 'pages', p);
  fs.readFile(file, (err, buf) => {
    if (err) { res.writeHead(404); res.end('not found'); return; }
    const ext = path.extname(file);
    const type = ext === '.html' ? 'text/html; charset=utf-8'
      : ext === '.js' ? 'application/javascript'
      : ext === '.css' ? 'text/css' : 'text/plain';
    res.writeHead(200, { 'Content-Type': type });
    res.end(buf);
  });
});

server.listen(port, '127.0.0.1', () => console.log(`serving ${root}/pages at http://127.0.0.1:${port}`));
