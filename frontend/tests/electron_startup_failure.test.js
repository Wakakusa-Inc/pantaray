const assert = require('assert');
const { test } = require('node:test');

const { reportFatalStartupFailure } = require('../electron/dist/main_runtime/startupFailure.js');

test('startup failure reporter surfaces fatal runtime config errors and quits packaged app', () => {
  const errors = [];
  const dialogs = [];
  let quitCalls = 0;

  reportFatalStartupFailure({
    app: {
      isPackaged: true,
      quit: () => {
        quitCalls += 1;
      },
    },
    dialog: {
      showErrorBox: (title, body) => {
        dialogs.push({ title, body });
      },
    },
    error: new Error('missing helper runtime metadata'),
    getUiLanguage: () => 'en',
    kind: 'runtime-config',
    logger: {
      error: (name, payload) => {
        errors.push({ name, payload });
      },
    },
    quitPackagedApp: true,
    stage: 'local-backend-runtime-config',
  });

  assert.equal(errors[0].name, 'APP_STARTUP_ERR');
  assert.equal(errors[0].payload.stage, 'local-backend-runtime-config');
  assert.equal(dialogs[0].title, 'Pantaray startup configuration error');
  assert.match(dialogs[0].body, /missing helper runtime metadata/);
  assert.equal(quitCalls, 1);
});

test('startup failure reporter still quits packaged app when the dialog fails', () => {
  const errors = [];
  let quitCalls = 0;

  reportFatalStartupFailure({
    app: {
      isPackaged: true,
      quit: () => {
        quitCalls += 1;
      },
    },
    dialog: {
      showErrorBox: () => {
        throw new Error('dialog unavailable');
      },
    },
    error: new Error('missing helper runtime metadata'),
    getUiLanguage: () => 'en',
    kind: 'runtime-config',
    logger: {
      error: (name, payload) => {
        errors.push({ name, payload });
      },
    },
    quitPackagedApp: true,
    stage: 'local-backend-runtime-config',
  });

  assert.deepStrictEqual(
    errors.map((entry) => entry.name),
    ['APP_STARTUP_ERR', 'APP_STARTUP_DIALOG_ERR']
  );
  assert.equal(quitCalls, 1);
});
