const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { createHash } = require('node:crypto');
const { stageEmbeddingModel } = require('../scripts/stage-embedding-model');

const MODEL_BYTES = Buffer.from('not a real graph');
const TOKENIZER_BYTES = Buffer.from('not a real tokenizer');

function digestOf(bytes) {
  return createHash('sha256').update(bytes).digest('hex');
}

function buildRelease() {
  return {
    modelId: 'example/embedding-model',
    sourceRevision: '0'.repeat(40),
    files: [
      {
        sourcePath: 'onnx/model_int8.onnx',
        installName: 'model.onnx',
        sha256: digestOf(MODEL_BYTES),
        bytes: MODEL_BYTES.length,
      },
      {
        sourcePath: 'tokenizer.json',
        installName: 'tokenizer.json',
        sha256: digestOf(TOKENIZER_BYTES),
        bytes: TOKENIZER_BYTES.length,
      },
    ],
    manifest: {
      model_id: 'example/embedding-model',
      source_revision: '0'.repeat(40),
      model_slug: 'example-int8',
      artifact_revision: '0123456789abcdef',
      model_file: 'model.onnx',
      model_sha256: digestOf(MODEL_BYTES),
      tokenizer_file: 'tokenizer.json',
      tokenizer_sha256: digestOf(TOKENIZER_BYTES),
      dimensions: 384,
      max_tokens: 512,
      max_text_chars: 512,
      pooling: 'mean',
      query_prefix: 'query: ',
      document_prefix: 'passage: ',
    },
  };
}

function fixture(t, release = buildRelease()) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'stage-embedding-model-test-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const releasePath = path.join(root, 'release.json');
  fs.writeFileSync(releasePath, JSON.stringify(release));
  const stagingDir = path.join(root, 'staged');
  fs.mkdirSync(stagingDir);
  fs.writeFileSync(path.join(stagingDir, 'previous'), 'preserve');
  const requested = [];
  const serve =
    (bytesByPath = { 'onnx/model_int8.onnx': MODEL_BYTES, 'tokenizer.json': TOKENIZER_BYTES }) =>
    async (url) => {
      requested.push(url);
      const match = Object.entries(bytesByPath).find(([sourcePath]) => url.endsWith(sourcePath));
      return match ? new Response(match[1]) : new Response('', { status: 404 });
    };
  return {
    root,
    requested,
    serve,
    options: {
      releasePath,
      stagingDir,
      cacheDir: path.join(root, 'cache'),
      fetchArtifact: serve(),
    },
  };
}

test('stages the pinned files and the manifest the runtime reads', async (t) => {
  const { options, requested } = fixture(t);

  await stageEmbeddingModel(options);

  assert.deepEqual(fs.readdirSync(options.stagingDir).sort(), [
    'manifest.json',
    'model.onnx',
    'tokenizer.json',
  ]);
  assert.deepEqual(fs.readFileSync(path.join(options.stagingDir, 'model.onnx')), MODEL_BYTES);
  assert.equal(
    JSON.parse(fs.readFileSync(path.join(options.stagingDir, 'manifest.json'), 'utf8'))
      .artifact_revision,
    '0123456789abcdef'
  );
  assert.deepEqual(requested, [
    'https://huggingface.co/example/embedding-model/resolve/0000000000000000000000000000000000000000/onnx/model_int8.onnx',
    'https://huggingface.co/example/embedding-model/resolve/0000000000000000000000000000000000000000/tokenizer.json',
  ]);
});

test('a second run stages from the cache without fetching', async (t) => {
  const { options, requested } = fixture(t);
  await stageEmbeddingModel(options);
  requested.length = 0;

  await stageEmbeddingModel(options);

  assert.deepEqual(requested, []);
  assert.deepEqual(
    fs.readFileSync(path.join(options.stagingDir, 'tokenizer.json')),
    TOKENIZER_BYTES
  );
});

test('a served file that differs from its digest fails the build', async (t) => {
  const { options, serve, root } = fixture(t);
  options.fetchArtifact = serve({
    'onnx/model_int8.onnx': Buffer.from('tampered'),
    'tokenizer.json': TOKENIZER_BYTES,
  });

  await assert.rejects(stageEmbeddingModel(options), /SHA256 mismatch/);

  assert.deepEqual(fs.readdirSync(options.stagingDir), ['previous']);
  assert.deepEqual(fs.readdirSync(options.cacheDir), []);
  assert.ok(!fs.readdirSync(root).some((name) => name.startsWith('.embedding-model-stage-')));
});

test('a cached file that no longer matches its digest is fetched again', async (t) => {
  const { options, requested } = fixture(t);
  await stageEmbeddingModel(options);
  const cachedModel = path.join(options.cacheDir, digestOf(MODEL_BYTES));
  fs.writeFileSync(cachedModel, Buffer.from('rotted bytes....'));
  requested.length = 0;

  await stageEmbeddingModel(options);

  assert.equal(requested.length, 1);
  assert.deepEqual(fs.readFileSync(path.join(options.stagingDir, 'model.onnx')), MODEL_BYTES);
});

for (const [name, corrupt] of [
  [
    'a manifest naming another model',
    (release) => {
      release.manifest.model_id = 'example/other-model';
    },
  ],
  [
    'a manifest naming another revision',
    (release) => {
      release.manifest.source_revision = '1'.repeat(40);
    },
  ],
  [
    'a digest the manifest does not share',
    (release) => {
      release.files[0].sha256 = digestOf(Buffer.from('some other graph'));
    },
  ],
  [
    'a file the manifest never names',
    (release) => {
      release.files.push({ ...release.files[1], installName: 'extra.json' });
    },
  ],
  [
    'a manifest file that is not staged',
    (release) => {
      release.files.pop();
    },
  ],
]) {
  test(`${name} fails before anything is fetched`, async (t) => {
    const release = buildRelease();
    corrupt(release);
    const { options } = fixture(t, release);
    options.fetchArtifact = () => assert.fail('must not fetch against an inconsistent pin');

    await assert.rejects(stageEmbeddingModel(options), /Embedding model pin/);

    assert.deepEqual(fs.readdirSync(options.stagingDir), ['previous']);
  });
}
