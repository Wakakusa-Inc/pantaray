const assert = require('node:assert/strict');
const { spawnSync } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { test } = require('node:test');

test('source control wire fixtures conform to the Electron discriminated unions', () => {
  const root = path.resolve(__dirname, '..');
  const fixtures = JSON.parse(
    fs.readFileSync(path.join(root, 'shared/context_source.fixtures.json'), 'utf8')
  );
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'pantaray-context-contract-'));
  try {
    const contract = path.join(root, 'shared/context_source');
    const source = `
      import type { SourceTransition, SourceTransitionResult } from ${JSON.stringify(contract)};
      const requests = ${JSON.stringify(fixtures.transitions)} satisfies Record<string, SourceTransition>;
      const results = ${JSON.stringify(fixtures.results)} satisfies Record<string, SourceTransitionResult>;
      function acceptsRequest(request: SourceTransition): void {
        switch (request.kind) {
          case 'suspend': return;
          case 'activate': return;
          case 'set_capture_paused': return;
          default: request satisfies never;
        }
      }
      function acceptsResult(result: SourceTransitionResult): void {
        switch (result.kind) {
          case 'applied': return;
          case 'conflict': return;
          case 'blocked': return;
          default: result satisfies never;
        }
      }
      const { expected_epoch, ...unboundSuspend } = requests.suspend;
      // @ts-expect-error delayed suspend requests must identify their target generation
      const missingEpoch: SourceTransition = unboundSuspend;
      // @ts-expect-error blocked outcomes must use the blocked outer discriminator
      const blockedSuccess: SourceTransitionResult = { kind: "applied", state: results.blocked.state };
      // @ts-expect-error callers must not select an executable
      const arbitraryPath: SourceTransition = { ...requests.activate, executable: '/tmp/tool' };
      // @ts-expect-error a new protocol needs an explicit contract upgrade
      const incompatible: SourceTransition = { ...requests.activate, recorder_binding: { store_id: 'store', protocol_version: 2 } };
    `;
    const file = path.join(dir, 'contract.ts');
    fs.writeFileSync(file, source);
    const result = spawnSync(
      process.execPath,
      [require.resolve('typescript/bin/tsc'), '--strict', '--noEmit', '--skipLibCheck', file],
      { encoding: 'utf8' }
    );
    assert.equal(result.error, undefined);
    assert.equal(result.status, 0, result.stdout + result.stderr);
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});
