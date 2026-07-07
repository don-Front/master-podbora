import { chromium } from 'playwright';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..', '..');
const testUrl = process.env.WIDGET_TEST_URL || 'http://127.0.0.1:10113/test-embed-resize.html';

async function main() {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });

  await page.goto(testUrl, { waitUntil: 'networkidle', timeout: 30000 });

  const iframe = page.frameLocator('#turbo-don-widget-frame');
  await iframe.locator('.chat-widget__toggle').click({ timeout: 15000 });
  await iframe.locator('.chat-widget__window--visible').waitFor({ timeout: 10000 });

  const metrics = await page.evaluate(async () => {
    const iframe = document.getElementById('turbo-don-widget-frame');
    const win = iframe.contentWindow;
    const doc = iframe.contentDocument;

    win.__dragMetrics = {
      viewportMsgs: 0,
      innerResizeEvents: 0,
      reactViewportVersions: 0,
    };

    win.addEventListener('message', (e) => {
      if (e.data && e.data.type === 'VIEWPORT') win.__dragMetrics.viewportMsgs++;
    });
    win.addEventListener('resize', () => {
      win.__dragMetrics.innerResizeEvents++;
    });

    const handle = doc.querySelector('.chat-widget__resize-handle--top');
    const rect = handle.getBoundingClientRect();
    const startX = rect.left + rect.width / 2;
    const startY = rect.top + rect.height / 2;
    const steps = 40;
    const deltaY = -180;

    const pointerDown = new PointerEvent('pointerdown', {
      bubbles: true,
      cancelable: true,
      pointerId: 1,
      clientX: startX,
      clientY: startY,
      pointerType: 'mouse',
    });
    handle.dispatchEvent(pointerDown);

    const frameTimes = [];
    let last = performance.now();

    for (let i = 1; i <= steps; i += 1) {
      const y = startY + (deltaY * i) / steps;
      handle.dispatchEvent(new PointerEvent('pointermove', {
        bubbles: true,
        cancelable: true,
        pointerId: 1,
        clientX: startX,
        clientY: y,
        pointerType: 'mouse',
      }));
      await new Promise((r) => requestAnimationFrame(r));
      const now = performance.now();
      frameTimes.push(now - last);
      last = now;
    }

    const viewportMsgsDuringDrag = win.__dragMetrics.viewportMsgs;
    const innerResizeEventsDuringDrag = win.__dragMetrics.innerResizeEvents;

    handle.dispatchEvent(new PointerEvent('pointerup', {
      bubbles: true,
      cancelable: true,
      pointerId: 1,
      clientX: startX,
      clientY: startY + deltaY,
      pointerType: 'mouse',
    }));

    await new Promise((r) => setTimeout(r, 200));

    const longFrames = frameTimes.filter((t) => t > 32).length;
    const avgFrame = frameTimes.reduce((a, b) => a + b, 0) / frameTimes.length;
    const maxFrame = Math.max(...frameTimes);
    const height = doc.querySelector('.chat-widget__window').getBoundingClientRect().height;

    return {
      height,
      steps,
      avgFrameMs: Number(avgFrame.toFixed(2)),
      maxFrameMs: Number(maxFrame.toFixed(2)),
      longFramesOver32ms: longFrames,
      viewportMsgsDuringDrag,
      innerResizeEventsDuringDrag,
    };
  });

  console.log(JSON.stringify(metrics, null, 2));

  const passed =
    metrics.height > 350 &&
    metrics.viewportMsgsDuringDrag === 0 &&
    metrics.innerResizeEventsDuringDrag <= 2 &&
    metrics.longFramesOver32ms <= 2 &&
    metrics.maxFrameMs < 80;

  await browser.close();

  if (!passed) {
    console.error('FAIL: resize jank detected');
    process.exit(1);
  }

  console.log('PASS: height resize is smooth');
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
