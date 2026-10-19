// Render an HTML canvas animation frame by frame: node render.js page.html out_dir seconds [fps] [--stills t1,t2,...]
const { chromium } = require('playwright-core');
const fs = require('fs');
const path = require('path');

(async () => {
  const [page_, outDir, secondsArg, fpsArg] = process.argv.slice(2);
  const stillsIdx = process.argv.indexOf('--stills');
  const stills = stillsIdx > 0 ? process.argv[stillsIdx + 1].split(',').map(Number) : null;
  const fps = Number(fpsArg || 30), seconds = Number(secondsArg);
  fs.mkdirSync(outDir, { recursive: true });
  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium-1194/chrome-linux/chrome',
    args: ['--allow-file-access-from-files'] });
  const page = await browser.newPage({ viewport: { width: 1080, height: 1080 } });
  page.on('pageerror', e => { console.error('page error:', e.message); process.exit(1); });
  await page.goto('file://' + path.resolve(page_));
  await page.evaluate(() => window.ready);
  const times = stills || Array.from({ length: Math.round(seconds * fps) }, (_, i) => i / fps);
  for (let i = 0; i < times.length; i++) {
    const data = await page.evaluate(t => { window.render(t); return document.getElementById('c').toDataURL('image/png'); }, times[i]);
    fs.writeFileSync(path.join(outDir, `f${String(i).padStart(5, '0')}.png`), Buffer.from(data.split(',')[1], 'base64'));
  }
  await browser.close();
  console.log(`rendered ${times.length} frame(s) to ${outDir}`);
})().catch(e => { console.error(e); process.exit(1); });
