#!/usr/bin/env node
/**
 * Real Chrome fullscreen composer regression. Required: MOTION_TEST_USERNAME,
 * MOTION_TEST_PASSWORD. FULLSCREEN_TEST_MODE=inspect collects existing layout;
 * =candidate injects the two local scoped styles; default =deployed.
 * Account preference PUTs receive 409; chat/TTS always use the real services.
 */
import assert from 'node:assert/strict';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const appRoot = resolve(here, '../..');
const localRequire = createRequire(join(appRoot, 'package.json'));
const globalRequire = createRequire(join(dirname(process.execPath), '..', 'lib/node_modules/agent-browser/package.json'));
let chromium;
try { ({ chromium } = localRequire('playwright-core')); } catch { ({ chromium } = globalRequire('playwright-core')); }
const base = new URL(process.env.BASE_URL ?? 'https://10.9.0.32:8787');
const mode = process.env.FULLSCREEN_TEST_MODE ?? 'deployed';
const out = resolve(process.env.MOTION_ARTIFACT_DIR ?? `/tmp/openvman-fullscreen-chat/${mode}`);
const username = process.env.MOTION_TEST_USERNAME;
const password = process.env.MOTION_TEST_PASSWORD;
const projectId = 'proj-9c042e94e0';
const report = { mode, baseURL: base.origin, startedAt: new Date().toISOString(), passed: false,
  layouts: [], checks: [], pageErrors: [], requests: [], preferenceWritesBlocked: 0,
  requestFailures: [], consoleMessages: [], chatResponses: [],
  limitations: ['偏好 PUT 409 隔離，不測遠端持久化。', '實體手機鍵盤未測；窄幅與短高採真實 Chrome viewport。'] };
let browser, context, page;
const diagnostics = [];
const sleep = (ms) => new Promise((done) => setTimeout(done, ms));
function pass(name) { report.checks.push({ name, passed: true }); console.log(`[PASS] ${name}`); }

async function boxes(label) {
  const result = await page.evaluate(() => {
    const selectors = ['.app-shell', '.kiosk-layout', '.control-area', '.chat-area', '.chat-panel', '.chat-messages',
      '.chat-input-bar', '.composer-shell', '.chat-input-bar input', '.chat-send-btn', '.asr-btn'];
    const values = {};
    for (const selector of selectors) {
      const node = document.querySelector(selector);
      if (!node) continue;
      const rect = node.getBoundingClientRect(); const css = getComputedStyle(node);
      const hit = document.elementFromPoint(rect.x + rect.width / 2, rect.y + rect.height / 2);
      values[selector] = { x: rect.x, y: rect.y, width: rect.width, height: rect.height,
        right: rect.right, bottom: rect.bottom, clientWidth: node.clientWidth, scrollWidth: node.scrollWidth,
        clientHeight: node.clientHeight, scrollHeight: node.scrollHeight,
        background: css.backgroundColor, color: css.color, borderColor: css.borderColor,
        borderWidth: css.borderWidth, flex: css.flex, flexWrap: css.flexWrap,
        minWidth: css.minWidth, minHeight: css.minHeight, maxHeight: css.maxHeight,
        overflow: css.overflow, position: css.position, hitClass: hit?.className,
        centerReachable: hit === node || node.contains(hit),
        disabled: node instanceof HTMLButtonElement ? node.disabled : undefined,
      };
    }
    return { viewport: { width: innerWidth, height: innerHeight }, fullscreen: Boolean(document.fullscreenElement),
      immersive: document.querySelector('.app-shell')?.classList.contains('immersive'),
      documentWidth: document.documentElement.scrollWidth, values };
  });
  report.layouts.push({ label, ...result });
  await page.screenshot({ path: join(out, `${label}.png`), fullPage: false });
  return result;
}

function assertComposer(result, enabled) {
  const { values: v, viewport } = result;
  const bar = v['.chat-input-bar'], input = v['.chat-input-bar input'], button = v['.chat-send-btn'];
  assert.ok(result.immersive && result.fullscreen, '沒有透過正式全螢幕按鈕進入瀏覽器 fullscreen');
  assert.ok(result.documentWidth <= viewport.width + 1, '頁面水平溢出');
  for (const [name, box] of [['input', input], ['button', button], ['microphone', v['.asr-btn']]]) {
    if (!box) continue;
    assert.ok(box.width > 0 && box.height >= 40 && box.x >= -1 && box.right <= viewport.width + 1
      && box.y >= 0 && box.bottom <= viewport.height + 1, `${name}: 不完整顯示在視窗內`);
    assert.ok(box.centerReachable, `${name}: 中央被其他圖層遮住`);
    assert.ok(box.y >= bar.y - 1 && box.bottom <= bar.bottom + 1, `${name}: 超出輸入列`);
  }
  assert.ok(input.width >= 80 && v['.composer-shell'].scrollWidth <= v['.composer-shell'].clientWidth + 1,
    '輸入框無法在 flex 中縮小');
  assert.ok(bar.scrollWidth <= bar.clientWidth + 1, '輸入列內容水平溢出');
  assert.ok(Math.abs(input.y - button.y) <= 3, '輸入與送出/停止未在同一列');
  assert.equal(button.disabled, !enabled, '空白/有字的按鈕 disabled 行為錯誤');
  assert.ok(!['rgba(0, 0, 0, 0)', 'transparent'].includes(button.background), '送出/停止背景透明');
  assert.ok(!['rgba(0, 0, 0, 0)', 'transparent'].includes(bar.background), '輸入列缺少獨立底色');
  assert.ok(v['.chat-area'].bottom <= viewport.height + 1 && bar.bottom <= v['.chat-area'].bottom + 1,
    '全螢幕聊天高度限制把輸入列裁掉');
}

async function injectCandidate() {
  const { compileStyle } = localRequire('@vue/compiler-sfc');
  const appScope = await page.locator('.app-shell').evaluate((node) => node.getAttributeNames().find((name) => name.startsWith('data-v-')));
  for (const [selector, file, sfc] of [
    ['.app-shell', 'src/styles/app-shell.css', false],
    ['.chat-panel', 'src/components/chat/ChatPanel.vue', true],
  ]) {
    const scope = await page.locator(selector).evaluate((node, parentScope) => node.getAttributeNames()
      .find((name) => name.startsWith('data-v-') && (node.matches('.app-shell') || name !== parentScope)), appScope);
    assert.ok(scope, `${selector}: 找不到實際 Vue scope`);
    const content = await readFile(join(appRoot, file), 'utf8');
    const source = sfc ? content.match(/<style scoped>([\s\S]*?)<\/style>/)[1] : content;
    const compiled = compileStyle({ id: scope, source, scoped: true, filename: file });
    assert.deepEqual(compiled.errors, []);
    await page.addStyleTag({ content: compiled.code });
  }
  report.candidateStylesInjected = true;
}

await mkdir(out, { recursive: true });
try {
  assert.ok(username && password, '請設定 MOTION_TEST_USERNAME/PASSWORD。');
  browser = await chromium.launch({ executablePath: '/usr/bin/google-chrome', headless: true,
    args: ['--no-sandbox', '--autoplay-policy=no-user-gesture-required'] });
  context = await browser.newContext({ ignoreHTTPSErrors: true, viewport: { width: 1440, height: 900 }, serviceWorkers: 'block' });
  await context.route('**/*', async (route) => {
    const request = route.request(); const path = new URL(request.url()).pathname;
    if (path === '/api/v1/settings/my-preferences' && request.method() === 'PUT') {
      report.preferenceWritesBlocked++;
      return route.fulfill({ status: 409, contentType: 'application/json', body: '{"detail":"E2E preference isolation"}' });
    }
    if (['/api/v1/chat', '/api/v1/chat/stream'].includes(path) && request.method() === 'POST') {
      if (request.postDataJSON()?.project_id !== projectId) return route.abort('blockedbyclient');
    }
    return route.continue();
  });
  const login = await context.request.post(new URL('/api/v1/auth/login', base).href, {
    headers: { Origin: base.origin }, data: { username, password },
  });
  assert.ok(login.ok(), `登入 HTTP ${login.status()}`);
  page = await context.newPage();
  page.on('pageerror', (error) => report.pageErrors.push(error.message));
  page.on('requestfailed', (request) => report.requestFailures.push({
    at: new Date().toISOString(), url: request.url(), method: request.method(),
    resourceType: request.resourceType(), error: request.failure()?.errorText,
  }));
  page.on('console', (message) => {
    if (!['warning', 'error'].includes(message.type())) return;
    const entry = { at: new Date().toISOString(), type: message.type(),
      text: message.text().slice(0, 12000), location: message.location(), args: [] };
    report.consoleMessages.push(entry);
    diagnostics.push(Promise.all(message.args().map(async (arg) => {
      try {
        const value = await arg.evaluate((item) => item instanceof Error
          ? { name: item.name, message: item.message, stack: item.stack } : item);
        const encoded = JSON.stringify(value);
        return encoded?.length > 12000 ? encoded.slice(0, 12000) : value;
      } catch (error) { return { captureError: error.message }; }
    })).then((args) => { entry.args = args; }));
  });
  page.on('response', (response) => {
    const path = new URL(response.url()).pathname;
    if (/chat|speech|tts/.test(path)) report.requests.push({ path, status: response.status(), method: response.request().method() });
    if (/^\/api\/v1\/chat(?:\/|$)/.test(path) && response.request().method() === 'POST') {
      const entry = { at: new Date().toISOString(), path, status: response.status(),
        contentType: response.headers()['content-type'] };
      report.chatResponses.push(entry);
      diagnostics.push((async () => {
        try {
          const failure = await response.finished();
          if (failure) entry.transportError = failure.message;
          entry.body = (await response.text()).slice(0, 32000);
          entry.bodyCapturedAt = new Date().toISOString();
        } catch (error) { entry.bodyCaptureError = error.message; }
      })());
    }
  });
  await page.goto(new URL('/?kiosk=0', base).href, { waitUntil: 'domcontentloaded' });
  await page.getByRole('button', { name: '系統設定', exact: true }).waitFor({ timeout: 120000 });
  await page.getByRole('button', { name: '系統設定', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: '系統設定', exact: true });
  const projectField = dialog.locator('.field-card').filter({ has: page.locator('.field-card__label', { hasText: '大腦/知識庫' }) }).getByRole('combobox');
  if (!(await projectField.innerText()).includes('元復醫院')) {
    await projectField.click();
    await dialog.getByRole('option', { name: '元復醫院', exact: true }).click();
  }
  await dialog.locator('.btn-apply').click();
  await sleep(500);
  if (await dialog.isVisible()) {
    await dialog.getByRole('button', { name: '取消', exact: true }).click();
    report.settingsDialogClosedAfterApply = true;
  }
  await dialog.waitFor({ state: 'hidden' });
  await page.waitForFunction(() => !document.querySelector('.avatar-overlay.loading')
    && !document.querySelector('.chat-input-bar input').disabled, null, { timeout: 120000 });
  if (mode === 'candidate') await injectCandidate();
  await page.getByRole('button', { name: '全螢幕', exact: true }).click();
  await page.waitForFunction(() => document.querySelector('.app-shell.immersive') && document.fullscreenElement);
  const matrix = [[320, 568], [375, 667], [414, 736], [768, 1024], [1440, 900], [320, 360], [375, 360], [768, 360], [1440, 480]];
  for (const [width, height] of matrix) {
    await page.setViewportSize({ width, height }); await sleep(250);
    const input = page.locator('.chat-input-bar input');
    await input.fill(''); await input.blur(); await sleep(100);
    const empty = await boxes(`${width}x${height}-empty`);
    if (mode !== 'inspect') assertComposer(empty, false);
    await input.fill('測試輸入：你好，這是一段用來檢查窄畫面仍可縮放的文字。');
    await input.blur(); await sleep(100);
    const filled = await boxes(`${width}x${height}-filled`);
    if (mode !== 'inspect') assertComposer(filled, true);
    await input.fill('   '); await input.blur();
    assert.ok(await page.getByRole('button', { name: '送出', exact: true }).isDisabled(), '純空白可以送出');
    await input.fill('');
    if (mode !== 'inspect') pass(`${width}x${height}-empty-filled-whitespace`);
  }
  if (mode !== 'inspect') {
    await page.setViewportSize({ width: 375, height: 667 });
    await page.locator('.chat-input-bar input').fill('你好，請用三句簡短繁體中文打招呼，不提供醫療建議。');
    await page.getByRole('button', { name: '送出', exact: true }).click();
    const stop = page.getByRole('button', { name: '停止回答', exact: true });
    await stop.waitFor({ state: 'visible', timeout: 120000 });
    await page.locator('.chat-input-bar input').blur(); await sleep(100);
    assertComposer(await boxes('375x667-stopping'), true);
    await stop.click();
    await page.getByRole('button', { name: '送出', exact: true }).waitFor({ timeout: 15000 });
    assertComposer(await boxes('375x667-after-stop'), false);
    pass('real-send-and-stop-stays-visible');
    for (const [width, height] of matrix) {
      await page.setViewportSize({ width, height }); await sleep(150);
      assertComposer(await boxes(`${width}x${height}-conversation`), false);
    }
    pass('conversation-history-keeps-composer-visible-at-all-sizes');
    // This fixture verifies the existing alert markup's layout, not an API result.
    await page.evaluate(() => {
      const feedback = document.createElement('p');
      feedback.className = 'chat-input-feedback'; feedback.id = 'fullscreen-layout-feedback';
      feedback.setAttribute('role', 'alert');
      const bar = document.querySelector('.chat-input-bar');
      for (const attr of bar.getAttributeNames().filter((name) => name.startsWith('data-v-'))) feedback.setAttribute(attr, '');
      feedback.textContent = '目前尚未連線，內容已保留，請稍後再試。這段較長的錯誤說明也必須在輸入列內換行顯示。';
      bar.append(feedback);
    });
    for (const [width, height] of matrix) {
      await page.setViewportSize({ width, height }); await sleep(100);
      assertComposer(await boxes(`${width}x${height}-feedback-layout-fixture`), false);
      const fits = await page.locator('#fullscreen-layout-feedback').evaluate((node) => {
        const box = node.getBoundingClientRect(), bar = node.parentElement.getBoundingClientRect();
        return box.x >= bar.x && box.right <= bar.right && box.bottom <= bar.bottom && node.scrollWidth <= node.clientWidth + 1;
      });
      assert.ok(fits, '長文字 feedback 超出輸入列');
    }
    await page.locator('#fullscreen-layout-feedback').evaluate((node) => node.remove());
    pass('long-feedback-layout-fixture-keeps-controls-and-alert-within-bar');
    await page.getByRole('button', { name: '結束全螢幕', exact: true }).click();
    await page.waitForFunction(() => !document.querySelector('.app-shell.immersive'));
    await boxes('375x667-exit-fullscreen');
    assert.deepEqual(report.pageErrors, []);
  }
  report.passed = true;
} catch (error) {
  report.failure = { message: error.message, stack: error.stack };
  process.exitCode = 1;
  if (page) try {
    report.failure.visibleText = (await page.locator('body').innerText()).slice(0, 12000);
    await boxes('failure');
  } catch { /* Preserve original error. */ }
} finally {
  await context?.close(); await browser?.close();
  await Promise.allSettled(diagnostics);
  report.finishedAt = new Date().toISOString();
  await writeFile(join(out, 'report.json'), `${JSON.stringify(report, null, 2)}\n`);
  console.log(JSON.stringify({ passed: report.passed, mode, out, failure: report.failure?.message }, null, 2));
}
