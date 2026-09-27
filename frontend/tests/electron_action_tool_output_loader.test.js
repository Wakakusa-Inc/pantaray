const assert = require('assert');
const { test } = require('node:test');

const {
  ACTION_TOOL_OUTPUT_PAGE_LIMIT_BYTES,
  ActionToolOutputPaginationError,
  createActionToolOutputLoader,
} = require('../electron/dist/actions/actionToolOutputLoader.js');

const OUTPUT_KEY = { actionId: 'action/1', stepId: 'step/1' };

function textPage(content, nextCursor = null, truncated = false) {
  return {
    content,
    next_cursor: nextCursor,
    truncated,
    unavailable_reason: null,
  };
}

test('opaque cursor を変更せず Unicode output と truncated を連結する', async () => {
  const requests = [];
  const pages = [
    textPage('開始😀', 'opaque/一'),
    textPage('e\u0301\n', 'opaque/二'),
    textPage('終了', null, true),
  ];
  const loader = createActionToolOutputLoader(async (request) => {
    requests.push(request);
    return pages[requests.length - 1];
  });

  assert.deepStrictEqual(await loader.load(OUTPUT_KEY), {
    kind: 'text',
    content: '開始😀e\u0301\n終了',
    truncated: true,
  });
  assert.deepStrictEqual(
    requests.map(({ cursor, limitBytes }) => ({ cursor, limitBytes })),
    [
      { cursor: null, limitBytes: ACTION_TOOL_OUTPUT_PAGE_LIMIT_BYTES },
      { cursor: 'opaque/一', limitBytes: ACTION_TOOL_OUTPUT_PAGE_LIMIT_BYTES },
      { cursor: 'opaque/二', limitBytes: ACTION_TOOL_OUTPUT_PAGE_LIMIT_BYTES },
    ]
  );
  assert.ok(
    requests.every(({ actionId, stepId }) => actionId === 'action/1' && stepId === 'step/1')
  );
});

test('同じ Action/step の pending と completed load を共有し clear 後だけ再取得する', async () => {
  let resolveFirst;
  const firstPage = new Promise((resolve) => {
    resolveFirst = resolve;
  });
  let reads = 0;
  const loader = createActionToolOutputLoader(async ({ stepId }) => {
    reads += 1;
    if (reads === 1) return firstPage;
    return textPage(stepId);
  });

  const first = loader.load(OUTPUT_KEY);
  const concurrent = loader.load({ ...OUTPUT_KEY });
  assert.equal(reads, 1);
  resolveFirst(textPage('shared'));
  assert.deepStrictEqual(await Promise.all([first, concurrent]), [
    { kind: 'text', content: 'shared', truncated: false },
    { kind: 'text', content: 'shared', truncated: false },
  ]);
  assert.equal((await loader.load(OUTPUT_KEY)).content, 'shared');
  assert.equal(reads, 1);
  assert.equal((await loader.load({ ...OUTPUT_KEY, stepId: 'step/2' })).content, 'step/2');
  assert.equal(reads, 2);

  loader.clear();
  assert.equal((await loader.load(OUTPUT_KEY)).content, 'step/1');
  assert.equal(reads, 3);
});

test('失敗を cache し explicit retry だけが cursor null から再取得する', async () => {
  const failure = new Error('private transport detail');
  const requests = [];
  const loader = createActionToolOutputLoader(async (request) => {
    requests.push(request);
    if (requests.length === 1) throw failure;
    return textPage('recovered');
  });

  await assert.rejects(loader.load(OUTPUT_KEY), (error) => error === failure);
  await assert.rejects(loader.load({ ...OUTPUT_KEY }), (error) => error === failure);
  assert.equal(requests.length, 1);
  assert.deepStrictEqual(await loader.retry(OUTPUT_KEY), {
    kind: 'text',
    content: 'recovered',
    truncated: false,
  });
  assert.deepStrictEqual(
    requests.map(({ cursor }) => cursor),
    [null, null]
  );
});

test('no_output と binary を unavailable のまま返す', async () => {
  for (const reason of ['no_output', 'binary']) {
    let reads = 0;
    const loader = createActionToolOutputLoader(async () => {
      reads += 1;
      return { content: '', next_cursor: null, truncated: false, unavailable_reason: reason };
    });

    assert.deepStrictEqual(await loader.load(OUTPUT_KEY), { kind: 'unavailable', reason });
    assert.equal(reads, 1);
  }
});

test('同じ non-null cursor の再出現を拒否して読み込みを停止する', async () => {
  let reads = 0;
  const loader = createActionToolOutputLoader(async () => {
    reads += 1;
    return textPage(`page-${reads}`, 'repeated-cursor');
  });

  await assert.rejects(
    loader.load(OUTPUT_KEY),
    (error) => error instanceof ActionToolOutputPaginationError
  );
  assert.equal(reads, 2);
});
