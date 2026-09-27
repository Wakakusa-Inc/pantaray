const fs = require('node:fs');
const path = require('node:path');
const { createHash } = require('node:crypto');
const { LOCAL_EMBEDDING_MODEL_DIRNAME } = require('../electron/local_backend_runtime_bundle.js');

const RELEASE_PATH = path.resolve(__dirname, '../electron/embedding_model_release.json');
const EMBEDDING_MODEL_STAGING_DIR = path.resolve(
  __dirname,
  '..',
  '.generated',
  LOCAL_EMBEDDING_MODEL_DIRNAME
);
// Content-addressed, so a model swap cannot be served a stale file and the
// previous model's files stay usable when switching back.
const EMBEDDING_MODEL_CACHE_DIR = path.resolve(
  __dirname,
  '..',
  '.cache',
  LOCAL_EMBEDDING_MODEL_DIRNAME
);
const MODEL_FILE_BASE_URL = 'https://huggingface.co';
// `LOCAL_EMBEDDING_MANIFEST_FILENAME` in
// `agents/src/pantaray_agents/local_runtime/embedding_local/manifest.py`.
const MANIFEST_FILENAME = 'manifest.json';
// The graph alone is over 100 MB, and this runs on home connections as well as
// on release runners.
const DOWNLOAD_TIMEOUT_MS = 600000;

/**
 * Refuse a pin that describes two different models before anything is fetched.
 *
 * The local runtime reads the manifest and nothing else, so a `files` entry the
 * manifest does not name would be staged and then ignored, and a digest that
 * differs from the manifest's would stage a file the runtime refuses. Both mean
 * the pin was edited by hand instead of taken from the preparation script.
 */
function assertPinIsSelfConsistent(release) {
  const { modelId, sourceRevision, files, manifest } = release;
  if (manifest.model_id !== modelId || manifest.source_revision !== sourceRevision) {
    throw new Error(
      `Embedding model pin names ${modelId}@${sourceRevision}, ` +
        `its manifest names ${manifest.model_id}@${manifest.source_revision}`
    );
  }
  const expectedDigests = new Map([
    [manifest.model_file, manifest.model_sha256],
    [manifest.tokenizer_file, manifest.tokenizer_sha256],
  ]);
  if (files.length !== expectedDigests.size) {
    throw new Error(
      `Embedding model pin stages ${files.length} files, but its manifest names ${expectedDigests.size}`
    );
  }
  for (const file of files) {
    const expectedDigest = expectedDigests.get(file.installName);
    if (expectedDigest === undefined) {
      throw new Error(
        `Embedding model pin stages ${file.installName}, which its manifest never names`
      );
    }
    if (expectedDigest !== file.sha256) {
      throw new Error(
        `Embedding model pin and manifest disagree on the digest of ${file.installName}`
      );
    }
  }
}

function digestOf(bytes) {
  return createHash('sha256').update(bytes).digest('hex');
}

function isCached(cachePath, file) {
  if (!fs.existsSync(cachePath) || fs.statSync(cachePath).size !== file.bytes) {
    return false;
  }
  return digestOf(fs.readFileSync(cachePath)) === file.sha256;
}

async function fetchPinnedFile(file, { release, fetchArtifact }) {
  const url = `${MODEL_FILE_BASE_URL}/${release.modelId}/resolve/${release.sourceRevision}/${file.sourcePath}`;
  const response = await fetchArtifact(url, {
    signal: AbortSignal.timeout(DOWNLOAD_TIMEOUT_MS),
  });
  if (!response.ok) {
    throw new Error(`Embedding model download failed: HTTP ${response.status} for ${url}`);
  }
  const bytes = Buffer.from(await response.arrayBuffer());
  const digest = digestOf(bytes);
  if (digest !== file.sha256) {
    throw new Error(
      `Embedding model file SHA256 mismatch for ${url}: expected=${file.sha256} actual=${digest}`
    );
  }
  return bytes;
}

async function ensureCachedFile(file, { release, cacheDir, fetchArtifact }) {
  const cachePath = path.join(cacheDir, file.sha256);
  if (isCached(cachePath, file)) {
    return cachePath;
  }
  fs.mkdirSync(cacheDir, { recursive: true });
  const bytes = await fetchPinnedFile(file, { release, fetchArtifact });
  const temporaryPath = `${cachePath}.partial`;
  fs.writeFileSync(temporaryPath, bytes);
  fs.renameSync(temporaryPath, cachePath);
  return cachePath;
}

/**
 * Put the pinned embedding model where the desktop app reads it.
 *
 * The three files are what `LOCAL_EMBEDDING_MODEL_DIR` must contain: the graph,
 * the tokenizer and the manifest that binds them to a profile id. Anything that
 * cannot be verified fails the build rather than staging a partial directory,
 * because a model the runtime refuses is reported as semantic search being
 * unavailable, which nobody would read as a broken build.
 */
async function stageEmbeddingModel({
  releasePath = RELEASE_PATH,
  stagingDir = EMBEDDING_MODEL_STAGING_DIR,
  cacheDir = EMBEDDING_MODEL_CACHE_DIR,
  fetchArtifact = fetch,
} = {}) {
  const release = JSON.parse(fs.readFileSync(releasePath, 'utf8'));
  assertPinIsSelfConsistent(release);

  const cachePaths = new Map();
  for (const file of release.files) {
    const cachePath = await ensureCachedFile(file, { release, cacheDir, fetchArtifact });
    cachePaths.set(file.installName, cachePath);
  }

  fs.mkdirSync(path.dirname(stagingDir), { recursive: true });
  const temporary = fs.mkdtempSync(path.join(path.dirname(stagingDir), '.embedding-model-stage-'));
  try {
    // The packaged app ships this directory as it is staged, and `mkdtemp`
    // creates it private to the building user.
    fs.chmodSync(temporary, 0o755);
    for (const [installName, cachePath] of cachePaths) {
      fs.copyFileSync(cachePath, path.join(temporary, installName));
    }
    fs.writeFileSync(
      path.join(temporary, MANIFEST_FILENAME),
      `${JSON.stringify(release.manifest, null, 2)}\n`
    );
    fs.rmSync(stagingDir, { recursive: true, force: true });
    fs.renameSync(temporary, stagingDir);
    return stagingDir;
  } finally {
    fs.rmSync(temporary, { recursive: true, force: true });
  }
}

if (require.main === module) {
  stageEmbeddingModel().then(
    (directory) => process.stdout.write(`Staged embedding model: ${directory}\n`),
    (error) => {
      process.stderr.write(`${error.message}\n`);
      process.exitCode = 1;
    }
  );
}

module.exports = { stageEmbeddingModel };
