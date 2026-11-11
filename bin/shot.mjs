#!/usr/bin/env node
/**
 * Full-page mobile screenshot via Chrome DevTools Protocol — no clipping.
 *
 * Usage:
 *   node bin/shot.mjs <url> <out.png> [width] [scale]
 *
 * Unlike a plain `--window-size=390,900` capture (which clips at 900px), this
 * asks Chrome for the TRUE content height, emulates a mobile viewport at that
 * height, and captures the entire scrollable page with captureBeyondViewport.
 *
 * It also prints an OVERFLOW REPORT: every element whose right edge exceeds
 * the viewport width, so misalignment can be caught without eyeballing pixels.
 *
 * Default width 390 (iPhone), scale 2 (retina-crisp).
 */
import { spawn } from 'node:child_process';
import { writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const PROJECT = join(dirname(fileURLToPath(import.meta.url)), '..');
const PORT = 9444;
const PROFILE = join(PROJECT, 'tmp', 'chrome-profile-node');

const [url, out, widthArg = '390', scaleArg = '2'] = process.argv.slice(2);
const width = Number(widthArg);
const scale = Number(scaleArg);

function sleep(ms) { return new Promise((r) => setTimeout(r, ms)); }

async function waitForPort(port, timeoutMs = 15000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    try {
      const res = await fetch(`http://127.0.0.1:${port}/json/version`);
      if (res.ok) return;
    } catch {}
    await sleep(200);
  }
  throw new Error('Chrome debugging port did not come up');
}

const chrome = spawn(CHROME, [
  '--headless=new',
  '--disable-gpu',
  '--no-first-run',
  '--hide-scrollbars',
  `--remote-debugging-port=${PORT}`,
  '--remote-allow-origins=*',
  `--user-data-dir=${PROFILE}`,
  'about:blank',
], { stdio: 'ignore' });

let ws;
try {
  await waitForPort(PORT);
  // Open a new tab to the target URL.
  const created = await (await fetch(`http://127.0.0.1:${PORT}/json/new?${encodeURIComponent(url)}`, { method: 'PUT' })).json();
  ws = new WebSocket(created.webSocketDebuggerUrl);
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });

  let msgId = 0;
  const pending = new Map();
  ws.onmessage = (e) => {
    const msg = JSON.parse(e.data);
    if (msg.id && pending.has(msg.id)) {
      pending.get(msg.id)(msg);
      pending.delete(msg.id);
    }
  };
  const cmd = (method, params = {}) => new Promise((resolve, reject) => {
    const id = ++msgId;
    pending.set(id, (msg) => msg.error ? reject(new Error(`${method}: ${JSON.stringify(msg.error)}`)) : resolve(msg.result));
    ws.send(JSON.stringify({ id, method, params }));
  });

  await cmd('Page.enable');
  await cmd('Runtime.enable');
  await cmd('Network.enable');

  // Wait for the page to settle (network idle-ish).
  await sleep(2500);

  // True full-page content size.
  const metrics = await cmd('Page.getLayoutMetrics');
  const css = metrics.cssContentSize;
  const fullHeight = Math.max(Math.ceil(css.height), 600);

  // Mobile viewport at the full content height + retina scale.
  await cmd('Emulation.setDeviceMetricsOverride', {
    width, height: fullHeight, deviceScaleFactor: scale,
    mobile: true, screenWidth: width, screenHeight: fullHeight,
  });
  await cmd('Emulation.setEmulatedMedia', { media: 'screen' });
  await sleep(500);

  // Overflow probe: elements overflowing the right edge of the viewport.
  // "My eyes" — catches clipped/horizontally-scrolling misalignment.
  try {
    const probe = await cmd('Runtime.evaluate', {
      expression: `(() => {
        const vw = document.documentElement.clientWidth;
        const results = [];
        document.querySelectorAll('*').forEach((el) => {
          const r = el.getBoundingClientRect();
          if (r.width >= 1 && r.right > vw + 1) {
            results.push({
              tag: el.tagName.toLowerCase(),
              cls: (el.className && String(el.className)).slice(0, 60) || '',
              rect: Math.round(r.left) + ',' + Math.round(r.right),
              by: Math.round(r.right - vw),
            });
          }
        });
        // Only keep the outermost per element to reduce noise.
        return { vw, tall: document.documentElement.scrollHeight, count: results.length, items: results.slice(0, 20) };
      })()`,
      returnByValue: true,
    });
    const ov = probe.result.value;
    if (ov.count > 0) {
      console.log(`\n⚠ OVERFLOW REPORT (viewport ${ov.vw}px, page ${ov.tall}px tall): ${ov.count} overflowing elements`);
      for (const it of ov.items) console.log(`   <${it.tag} class="${it.cls}"> spans ${it.rect} → ${it.by}px past right edge`);
    } else {
      console.log(`✓ No elements overflow the ${ov.vw}px viewport (page ${ov.tall}px tall).`);
    }
  } catch { /* probe is best-effort */ }

  // Full-page capture (no clipping).
  const shot = await cmd('Page.captureScreenshot', { format: 'png', captureBeyondViewport: true });
  writeFileSync(out, Buffer.from(shot.data, 'base64'));
  console.log(`wrote ${out} (${width}px x ${fullHeight}px @ ${scale}x)`);
} catch (err) {
  console.error('error:', err.message);
  process.exitCode = 1;
} finally {
  if (ws && ws.readyState === WebSocket.OPEN) ws.close();
  chrome.kill();
}
