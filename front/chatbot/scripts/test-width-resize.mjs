import { chromium } from 'playwright';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const testUrl = process.env.WIDGET_TEST_URL || 'http://127.0.0.1:10113/test-embed-resize.html';

async function main() {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });

  await page.goto(testUrl, { waitUntil: 'networkidle', timeout: 30000 });

  const iframeEl = page.locator('#turbo-don-widget-frame');
  const iframe = page.frameLocator('#turbo-don-widget-frame');

  await iframe.locator('.chat-widget__toggle').click({ timeout: 15000 });
  await iframe.locator('.chat-widget__panel--visible').waitFor({ timeout: 10000 });

  const beforeGrab = await iframeEl.boundingBox();
  const beforePanel = await iframe.locator('.chat-widget__panel').boundingBox();

  const metrics = await page.evaluate(async () => {
    const iframe = document.getElementById('turbo-don-widget-frame');
    const win = iframe.contentWindow;
    const doc = win.document;

    const handle = doc.querySelector('.chat-widget__resize-handle--left');
    const panel = doc.querySelector('.chat-widget__panel');
    const initialPanelWidth = panel.getBoundingClientRect().width;
    const initialPanelRight = panel.getBoundingClientRect().right;

    const rect = handle.getBoundingClientRect();
    const startX = rect.left + rect.width / 2;
    const startY = rect.top + rect.height / 2;

    handle.dispatchEvent(new PointerEvent('pointerdown', {
      bubbles: true,
      cancelable: true,
      pointerId: 1,
      clientX: startX,
      clientY: startY,
      pointerType: 'mouse',
    }));

    await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));

    const iframeRectAfterGrab = iframe.getBoundingClientRect();
    const panelAfterGrab = panel.getBoundingClientRect();
    const shellExpanded = doc.documentElement.classList.contains('chat-widget--shell-expanded');

    const deltaX = -160;
    const steps = 20;
    for (let i = 1; i <= steps; i += 1) {
      const x = startX + (deltaX * i) / steps;
      win.dispatchEvent(new PointerEvent('pointermove', {
        bubbles: true,
        cancelable: true,
        pointerId: 1,
        clientX: x,
        clientY: startY,
        pointerType: 'mouse',
      }));
      await new Promise((r) => requestAnimationFrame(r));
    }

    const panelDuringDrag = panel.getBoundingClientRect();
    const iframeDuringDrag = iframe.getBoundingClientRect();

    win.dispatchEvent(new PointerEvent('pointerup', {
      bubbles: true,
      cancelable: true,
      pointerId: 1,
      clientX: startX + deltaX,
      clientY: startY,
      pointerType: 'mouse',
    }));

    await new Promise((r) => setTimeout(r, 250));

    const panelAfterRelease = panel.getBoundingClientRect();
    const iframeAfterRelease = iframe.getBoundingClientRect();
    const shellAfterRelease = doc.documentElement.classList.contains('chat-widget--shell-expanded');

    return {
      initialPanelWidth: Number(initialPanelWidth.toFixed(1)),
      panelWidthAfterGrab: Number(panelAfterGrab.width.toFixed(1)),
      panelRightAfterGrab: Number(panelAfterGrab.right.toFixed(1)),
      initialPanelRight: Number(initialPanelRight.toFixed(1)),
      iframeWidthAfterGrab: Number(iframeRectAfterGrab.width.toFixed(1)),
      panelWidthDuringDrag: Number(panelDuringDrag.width.toFixed(1)),
      panelRightDuringDrag: Number(panelDuringDrag.right.toFixed(1)),
      iframeWidthDuringDrag: Number(iframeDuringDrag.width.toFixed(1)),
      panelWidthAfterRelease: Number(panelAfterRelease.width.toFixed(1)),
      iframeWidthAfterRelease: Number(iframeAfterRelease.width.toFixed(1)),
      panelRightAfterRelease: Number(panelAfterRelease.right.toFixed(1)),
      shellExpanded,
      shellAfterRelease,
      widthIncreased: panelAfterRelease.width > initialPanelWidth + 40,
      rightEdgeStable: Math.abs(panelAfterGrab.right - panelDuringDrag.right) < 4,
    };
  });

  console.log(JSON.stringify({ beforeGrab, beforePanel, metrics }, null, 2));

  const passed =
    metrics.shellExpanded &&
    !metrics.shellAfterRelease &&
    metrics.iframeWidthAfterGrab >= 1200 &&
    metrics.iframeWidthDuringDrag >= 1200 &&
    metrics.panelWidthAfterGrab >= 280 &&
    metrics.rightEdgeStable &&
    metrics.widthIncreased;

  await browser.close();

  if (!passed) {
    console.error('FAIL: width resize shell behavior incorrect');
    process.exit(1);
  }

  console.log('PASS: width resize shell behavior OK');
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
