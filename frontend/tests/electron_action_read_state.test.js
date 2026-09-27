const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { afterEach, test } = require('node:test');

const { createActionReadState } = require('../electron/dist/history/actionReadState.js');
const { resolveScopedSettingsPath } = require('../electron/dist/settings/scope.js');

const temporaryRoots = [];

function createTemporaryRoot() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'pantaray-action-read-state-'));
  temporaryRoots.push(root);
  return root;
}

function statePath(root, userId) {
  return resolveScopedSettingsPath({
    userDataDir: root,
    userId,
    fileName: 'action-read-state.json',
  });
}

const markViewed = (state, subjectId, actionId, completionEventId) =>
  state.markCompletionViewed({ subjectId, actionId, completionEventId });

afterEach(() => {
  for (const root of temporaryRoots.splice(0)) {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test('subject ごとに read state を分離し、reload と sign-out を反映する', () => {
  const root = createTemporaryRoot();
  const state = createActionReadState({ userDataDir: root });

  state.setSubject('user-a');
  const userASnapshot = state.snapshotCompletionUnread();
  assert.equal(userASnapshot('action-1', 'event-a'), true);
  markViewed(state, 'user-a', 'action-1', 'event-a');
  assert.equal(userASnapshot('action-1', 'event-a'), false);
  assert.equal(state.snapshotCompletionUnread()('action-1', 'event-a'), false);

  state.setSubject('user-b');
  assert.equal(state.snapshotCompletionUnread()('action-1', 'event-a'), true);
  assert.throws(() => markViewed(state, 'user-a', 'action-1', 'event-b'), /does not match/);
  markViewed(state, 'user-b', 'action-1', 'event-b');
  assert.equal(userASnapshot('action-1', 'event-b'), true);

  state.setSubject('user-a');
  assert.equal(state.snapshotCompletionUnread()('action-1', 'event-a'), false);
  assert.equal(state.snapshotCompletionUnread()('action-1', 'event-b'), true);

  const reloaded = createActionReadState({ userDataDir: root });
  reloaded.setSubject('user-a');
  assert.equal(reloaded.snapshotCompletionUnread()('action-1', 'event-a'), false);

  reloaded.setSubject(null);
  assert.equal(reloaded.snapshotCompletionUnread()('action-1', 'event-a'), false);
  assert.throws(
    () => markViewed(reloaded, 'user-a', 'action-1', 'event-a'),
    /does not match/
  );
  assert.equal(
    fs.existsSync(path.join(root, 'settings', '__logged_out__', 'action-read-state.json')),
    false
  );
});

test('malformed JSON・不正 shape・Action 重複は全体を未読として扱い、読み取りで書き換えない', () => {
  const root = createTemporaryRoot();
  const filePath = statePath(root, 'user-a');
  const invalidFiles = [
    '{broken',
    JSON.stringify({ version: 1, entries: [{ action_id: 'action-1' }] }),
    JSON.stringify({
      version: 1,
      entries: [
        { action_id: 'action-1', completion_event_id: 'event-a' },
        { action_id: 'action-1', completion_event_id: 'event-b' },
      ],
    }),
  ];

  for (const serialized of invalidFiles) {
    fs.writeFileSync(filePath, serialized);
    const state = createActionReadState({ userDataDir: root });
    state.setSubject('user-a');
    assert.equal(state.snapshotCompletionUnread()('action-1', 'event-a'), true);
    assert.equal(fs.readFileSync(filePath, 'utf8'), serialized);
  }
});

test('read I/O failure は新subjectを未読として保持する', () => {
  const state = createActionReadState({ userDataDir: createTemporaryRoot() });
  state.setSubject('user-a');
  markViewed(state, 'user-a', 'action-1', 'event-a');
  const readFileSync = fs.readFileSync;
  fs.readFileSync = () => assert.fail('read denied');
  try {
    assert.throws(() => state.setSubject('user-b'), /read denied/);
  } finally {
    fs.readFileSync = readFileSync;
  }
  assert.equal(state.snapshotCompletionUnread()('action-1', 'event-a'), false);
  assert.throws(() => markViewed(state, 'user-b', 'action-1', 'event-b'), /does not match/);
});

test('1,000 Action に prune し、更新した Action を newest として保持する', () => {
  const root = createTemporaryRoot();
  const filePath = statePath(root, 'user-a');
  const entries = Array.from({ length: 1_000 }, (_, index) => ({
    action_id: `action-${index}`,
    completion_event_id: `event-${index}`,
  }));
  fs.writeFileSync(filePath, JSON.stringify({ version: 1, entries }));
  const state = createActionReadState({ userDataDir: root });
  state.setSubject('user-a');

  markViewed(state, 'user-a', 'action-0', 'event-0-new');
  markViewed(state, 'user-a', 'action-1000', 'event-1000');

  const persisted = JSON.parse(fs.readFileSync(filePath, 'utf8'));
  assert.equal(persisted.entries.length, 1_000);
  assert.equal(
    persisted.entries.some((entry) => entry.action_id === 'action-1'),
    false
  );
  assert.deepEqual(persisted.entries.slice(-2), [
    { action_id: 'action-0', completion_event_id: 'event-0-new' },
    { action_id: 'action-1000', completion_event_id: 'event-1000' },
  ]);
});

test('atomic rename 失敗時は旧 disk/memory を保ち、temp を削除する', () => {
  const root = createTemporaryRoot();
  const state = createActionReadState({ userDataDir: root });
  state.setSubject('user-a');
  markViewed(state, 'user-a', 'action-1', 'event-old');
  const filePath = statePath(root, 'user-a');
  const oldDisk = fs.readFileSync(filePath, 'utf8');
  assert.equal(fs.statSync(filePath).mode & 0o777, 0o600);

  const renameSync = fs.renameSync;
  fs.renameSync = () => {
    throw new Error('rename failed');
  };
  try {
    assert.throws(() => markViewed(state, 'user-a', 'action-1', 'event-new'), /rename failed/);
  } finally {
    fs.renameSync = renameSync;
  }

  assert.equal(state.snapshotCompletionUnread()('action-1', 'event-old'), false);
  assert.equal(state.snapshotCompletionUnread()('action-1', 'event-new'), true);
  assert.equal(fs.readFileSync(filePath, 'utf8'), oldDisk);
  assert.equal(
    fs.readdirSync(path.dirname(filePath)).some((name) => name.endsWith('.tmp')),
    false
  );
});
