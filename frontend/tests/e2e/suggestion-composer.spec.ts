import { test, expect, type Page, type TestInfo } from '@playwright/test';
import { createServer, type ViteDevServer } from 'vite';
import type { OverlaySnapshotPayload } from '../../src/components/agent-overlay/model/overlayTypes';
import type { AcceptActionRequest } from '../../electron/src/orchestration/eventContracts';
import type { ActionMessageRequest } from '../../electron/src/actions/actionContracts';

// Render the production entry with deterministic IPC inputs; no backend, account, or live store.
let vite: ViteDevServer;
let baseUrl: string;
test.beforeAll(async () => {
  vite = await createServer({ server: { host: '127.0.0.1', port: 0 } });
  await vite.listen();
  baseUrl = vite.resolvedUrls!.local[0];
});
test.afterAll(async () => {
  await vite?.close();
});
test.use({ viewport: { width: 460, height: 800 }, locale: 'ja-JP', deviceScaleFactor: 2 });

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem('pantaray_ui_language', 'ja');
    const noop = () => {};
    Object.defineProperty(window, 'electron', {
      value: {
        ipcRenderer: { on: () => noop },
        approval: {
          getWorkspaceEditCommandPreference: async () => ({ approval_mode: 'prompt_each_time' }),
        },
        agentOverlay: {
          onSnapshot: (callback: (payload: OverlaySnapshotPayload) => void) => {
            const listener = (event: Event) =>
              callback((event as CustomEvent<OverlaySnapshotPayload>).detail);
            window.addEventListener('test:snapshot', listener);
            document.documentElement.dataset.snapshotReady = 'true';
            return () => window.removeEventListener('test:snapshot', listener);
          },
          resize: (height: number) => {
            document.documentElement.dataset.overlayHeight = String(height);
          },
        },
        orchestration: {
          onEvent: () => noop,
          onStatus: () => noop,
          acceptAction: async (request: AcceptActionRequest) => {
            document.documentElement.dataset.accepted = JSON.stringify(request);
          },
        },
        actions: {
          onConversationUpdated: () => noop,
          submitMessage: async (request: ActionMessageRequest) => {
            document.documentElement.dataset.submitted = JSON.stringify(request);
            return { kind: 'action_conflict' };
          },
        },
      },
    });
  });
});

async function showSuggestion(
  page: Page,
  kind: 'message_only' | 'action_offer',
  id = 'suggestion-1'
) {
  // prettier-ignore
  const payload: OverlaySnapshotPayload = { snapshot: {
    suggestionId: id, commandId: kind === 'action_offer' ? 'command-1' : null, interactionContract: kind,
    suggestionText: kind === 'message_only'
      ? '午後の打ち合わせ、前回のメモに気になる点が残っていました。\n\n決めたいことを先に整理しておくと、話を進めやすそうです。'
      : '午後の打ち合わせに向けて、前回のメモから未決事項をまとめておきましょうか。',
    reactionState: null, reactionTimestamp: null, actionPhase: 'idle', actionStatus: null,
    actionErrorCode: null, actionFailureStage: null, actionFailureMessagePublic: null,
    processId: null, actionId: null, updatedAt: '2026-09-11T00:00:00Z', lastSequence: 1, isLive: true,
  } };
  await expect(page.locator('html')).toHaveAttribute('data-snapshot-ready', 'true');
  await page.evaluate(
    (detail) => window.dispatchEvent(new CustomEvent('test:snapshot', { detail })),
    payload
  );
  await expect(page.getByText(payload.snapshot.suggestionText.split('\n')[0])).toBeVisible();
}

async function capture(page: Page, info: TestInfo, name: string) {
  await page.evaluate(async () => {
    await document.fonts.ready;
    await Promise.all(
      document
        .getAnimations()
        .filter((animation) => animation.effect?.getComputedTiming().iterations !== Infinity)
        .map((animation) => animation.finished)
    );
  });
  const panel = page.locator('[data-sharecard-root]');
  await expect
    .poll(async () => Number(await page.locator('html').getAttribute('data-overlay-height')))
    .toBeGreaterThanOrEqual(Math.ceil((await panel.boundingBox())!.height));
  await panel.screenshot({ path: info.outputPath(`${name}.png`), omitBackground: true });
}

test('comment: quiet entry, keyboard reveal, resize and reply', async ({ page }, info) => {
  await page.goto(`${baseUrl}notification.html`);
  await showSuggestion(page, 'message_only');
  await expect(page.getByRole('textbox')).toHaveCount(0);
  const reply = page.getByRole('button', { name: 'この提案に返信' });
  await capture(page, info, 'comment-collapsed');
  const initialHeight = (await page.locator('[data-sharecard-root]').boundingBox())!.height;
  await reply.focus();
  await page.keyboard.press('Enter');
  const input = page.getByRole('textbox', { name: 'メッセージ', exact: true });
  await expect(input).toBeFocused();
  await capture(page, info, 'comment-expanded');
  expect((await page.locator('[data-sharecard-root]').boundingBox())!.height).toBeGreaterThan(
    initialHeight
  );
  await input.fill('決めたいことを3つに整理して');
  await input.press('Enter');
  const request = JSON.parse((await page.locator('html').getAttribute('data-submitted'))!);
  expect(request.target).toMatchObject({ kind: 'new', reply_to_suggestion_id: 'suggestion-1' });
  expect(request.message.content).toBe('決めたいことを3つに整理して');
});

test('offer: inline decisions, expanded instructions and fresh suggestion reset', async ({
  page,
}, info) => {
  await page.goto(`${baseUrl}notification.html`);
  await showSuggestion(page, 'action_offer');
  const open = page.getByRole('button', { name: '追加の指示（任意）' });
  const accept = page.getByRole('button', { name: '承認', exact: true });
  await expect(page.getByRole('textbox')).toHaveCount(0);
  const iconBox = (await open.boundingBox())!;
  const acceptBox = (await accept.boundingBox())!;
  expect(
    Math.abs(iconBox.y + iconBox.height / 2 - acceptBox.y - acceptBox.height / 2)
  ).toBeLessThan(2);
  expect(acceptBox.x).toBeGreaterThan(iconBox.x + iconBox.width);
  await capture(page, info, 'offer-collapsed');
  await open.click();
  const input = page.getByRole('textbox', { name: '追加の指示（任意）' });
  await expect(input).toBeFocused();
  await input.fill('未決事項だけを、箇条書きでまとめて');
  await expect(page.getByRole('button', { name: '画像を追加' })).toBeVisible();
  await page.getByRole('button', { name: /ファイル編集・コマンド実行の権限/ }).click();
  await page.getByRole('menuitemradio', { name: /自動承認/ }).click();
  await capture(page, info, 'offer-expanded');
  const composerBox = (await page.locator('.overlay-composer').boundingBox())!;
  const expandedAcceptBox = (await accept.boundingBox())!;
  const dismissBox = (await page.getByRole('button', { name: '見送る', exact: true }).boundingBox())!;
  expect(expandedAcceptBox.y).toBeGreaterThan(composerBox.y + composerBox.height);
  expect(Math.abs(expandedAcceptBox.y - dismissBox.y)).toBeLessThan(2);
  expect(expandedAcceptBox.x).toBeGreaterThan(dismissBox.x + dismissBox.width);
  await showSuggestion(page, 'action_offer', 'suggestion-2');
  await expect(open).toBeVisible();
  await open.click();
  await expect(input).toHaveValue('');
  await expect(page.getByRole('button', { name: /権限: 毎回確認/ })).toBeVisible();
  await input.fill('未決事項だけを、箇条書きでまとめて');
  await accept.click();
  expect(JSON.parse((await page.locator('html').getAttribute('data-accepted'))!)).toMatchObject({
    suggestionId: 'suggestion-2',
    supplement: '未決事項だけを、箇条書きでまとめて',
    approvalMode: 'prompt_each_time',
    images: [],
  });
});

test('user-started Action opens the regular composer immediately', async ({ page }, info) => {
  await page.goto(`${baseUrl}notification.html?mode=standalone`);
  await expect(page.getByRole('textbox', { name: 'メッセージ', exact: true })).toBeFocused();
  await expect(page.getByRole('button', { name: 'この提案に返信' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: '画像を追加' })).toBeVisible();
  await capture(page, info, 'standalone-unchanged');
});

test('narrow English layout and reduced motion keep the controls reachable', async ({
  page,
}, info) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.setViewportSize({ width: 360, height: 640 });
  await page.addInitScript(() => localStorage.setItem('pantaray_ui_language', 'en'));
  await page.goto(`${baseUrl}notification.html`);
  await showSuggestion(page, 'action_offer');
  const open = page.getByRole('button', { name: 'Additional instructions (optional)' });
  const controlsId = await open.getAttribute('aria-controls');
  await open.focus();
  await page.keyboard.press('Space');
  await expect(
    page.getByRole('textbox', { name: 'Additional instructions (optional)' })
  ).toBeFocused();
  await expect(page.getByRole('button', { name: 'Accept', exact: true })).toBeInViewport();
  expect(
    await page.locator(`[id="${controlsId}"]`).evaluate((element) => element.getAnimations().length)
  ).toBe(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(360);
  await capture(page, info, 'offer-narrow-reduced-motion');
});
