const assert = require('node:assert/strict');
const { execFileSync } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');

function readPackageJson() {
  return JSON.parse(
    fs.readFileSync(path.resolve(__dirname, '..', 'package.json'), 'utf8')
  );
}

function collectChunkImports(assetsDir) {
  const graph = new Map();
  const chunkFilenames = fs
    .readdirSync(assetsDir)
    .filter((filename) => filename.endsWith('.js'));
  const chunkFilenameSet = new Set(chunkFilenames);

  for (const filename of chunkFilenames) {
    const content = fs.readFileSync(path.join(assetsDir, filename), 'utf8');
    const imports = [...content.matchAll(/from"\.\/([^"]+\.js)"/g)].map(
      (match) => match[1]
    );
    graph.set(
      filename,
      imports.filter((imported) => chunkFilenameSet.has(imported))
    );
  }
  return graph;
}

function findCycle(graph) {
  const visiting = new Set();
  const visited = new Set();
  const stack = [];

  function visit(node) {
    if (visiting.has(node)) {
      return [...stack.slice(stack.indexOf(node)), node];
    }
    if (visited.has(node)) {
      return null;
    }
    visiting.add(node);
    stack.push(node);
    for (const next of graph.get(node) || []) {
      if (!graph.has(next)) {
        continue;
      }
      const cycle = visit(next);
      if (cycle) {
        return cycle;
      }
    }
    stack.pop();
    visiting.delete(node);
    visited.add(node);
    return null;
  }

  for (const node of graph.keys()) {
    const cycle = visit(node);
    if (cycle) {
      return cycle;
    }
  }
  return null;
}

test('the web renderer build script does not force development NODE_ENV', () => {
  assert.ok(
    !readPackageJson().scripts['build:web'].includes('NODE_ENV=development'),
    'build:web must not force NODE_ENV=development'
  );
});

test('production renderer chunks do not have circular imports', () => {
  const outDir = fs.mkdtempSync(path.join(os.tmpdir(), 'pantaray-vite-build-'));
  try {
    execFileSync(
      process.execPath,
      ['./node_modules/vite/bin/vite.js', 'build', '--outDir', outDir, '--emptyOutDir'],
      {
        cwd: path.resolve(__dirname, '..'),
        env: {
          ...process.env,
          NODE_ENV: 'production',
          VITE_BASE: './',
        },
        stdio: 'pipe',
      }
    );
    const graph = collectChunkImports(path.join(outDir, 'assets'));
    const cycle = findCycle(graph);
    assert.equal(
      cycle,
      null,
      `renderer chunk import cycle detected: ${cycle?.join(' -> ')}`
    );
  } finally {
    fs.rmSync(outDir, { recursive: true, force: true });
  }
});
