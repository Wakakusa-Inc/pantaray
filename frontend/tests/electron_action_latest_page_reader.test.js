const assert = require('assert');
const { test } = require('node:test');

const {
  createActionLatestPageReader,
} = require('../electron/dist/actions/actionLatestPageReader.js');

function conversationPage(actionId, latestRunId) {
  return {
    action: {
      action_id: actionId,
      suggestion_id: null,
      status: 'processing',
      latest_run_id: latestRunId,
      approved_suggestion: null,
      resumable: false,
    },
    runs: [],
    unadopted_messages: [],
    next_cursor: null,
  };
}

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((onResolve, onReject) => {
    resolve = onResolve;
    reject = onReject;
  });
  return { promise, reject, resolve };
}

const flush = () => new Promise(setImmediate);

test('同じActionの並行callerはdirty後の最新pageを共有する', async () => {
  const reads = [];
  const reader = createActionLatestPageReader(() => {
    const pending = deferred();
    reads.push(pending);
    return pending.promise;
  });

  const firstCaller = reader.read('action-a');
  const joinedCaller = reader.read('action-a');
  assert.equal(firstCaller, joinedCaller);
  await flush();
  assert.equal(reads.length, 1);

  reads[0].resolve(conversationPage('action-a', 'run-old'));
  await flush();
  assert.equal(reads.length, 2);
  const latest = conversationPage('action-a', 'run-new');
  reads[1].resolve(latest);

  assert.deepStrictEqual(await Promise.all([firstCaller, joinedCaller]), [latest, latest]);
});

test('dirty中のread失敗は同じflightの次readで収束する', async () => {
  const reads = [];
  const reader = createActionLatestPageReader(() => {
    const pending = deferred();
    reads.push(pending);
    return pending.promise;
  });

  const firstCaller = reader.read('action-a');
  const joinedCaller = reader.read('action-a');
  await flush();
  reads[0].reject(new Error('first read failed'));
  await flush();
  assert.equal(reads.length, 2);

  const recovered = conversationPage('action-a', 'run-recovered');
  reads[1].resolve(recovered);
  assert.deepStrictEqual(await Promise.all([firstCaller, joinedCaller]), [recovered, recovered]);
});

test('dirtyなしの失敗はsurfaceし、後続readを新しいflightで開始する', async () => {
  const failure = new Error('backend unavailable');
  let attempts = 0;
  const recovered = conversationPage('action-a', 'run-recovered');
  const reader = createActionLatestPageReader(async () => {
    attempts += 1;
    if (attempts === 1) throw failure;
    return recovered;
  });

  await assert.rejects(reader.read('action-a'), (error) => error === failure);
  assert.deepStrictEqual(await reader.read('action-a'), recovered);
  assert.equal(attempts, 2);
});

test('異なるActionのflightは互いを待たない', async () => {
  const reads = new Map();
  const reader = createActionLatestPageReader((actionId) => {
    const pending = deferred();
    reads.set(actionId, pending);
    return pending.promise;
  });

  const actionA = reader.read('action-a');
  const actionB = reader.read('action-b');
  await flush();
  const pageB = conversationPage('action-b', 'run-b');
  reads.get('action-b').resolve(pageB);
  assert.deepStrictEqual(await actionB, pageB);

  const pageA = conversationPage('action-a', 'run-a');
  reads.get('action-a').resolve(pageA);
  assert.deepStrictEqual(await actionA, pageA);
});

test('clearは旧flightを切り離し、旧完了処理は新flightを削除しない', async () => {
  const reads = [];
  const reader = createActionLatestPageReader(() => {
    const pending = deferred();
    reads.push(pending);
    return pending.promise;
  });

  const oldSubject = reader.read('action-a');
  const joinedOldSubject = reader.read('action-a');
  assert.equal(reads.length, 1);
  reader.clear();
  const newSubject = reader.read('action-a');
  await flush();
  assert.equal(reads.length, 2);

  reads[0].resolve(conversationPage('action-a', 'run-old-subject'));
  await Promise.all([oldSubject, joinedOldSubject]);
  assert.equal(reads.length, 2);
  const joinedNewSubject = reader.read('action-a');
  assert.equal(joinedNewSubject, newSubject);

  reads[1].resolve(conversationPage('action-a', 'run-new-subject-old-page'));
  await flush();
  assert.equal(reads.length, 3);
  const latest = conversationPage('action-a', 'run-new-subject-latest');
  reads[2].resolve(latest);
  assert.deepStrictEqual(await Promise.all([newSubject, joinedNewSubject]), [latest, latest]);
});
