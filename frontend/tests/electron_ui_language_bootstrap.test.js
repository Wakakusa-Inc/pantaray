const assert = require('assert');
const { test } = require('node:test');

const {
  UI_LANGUAGE_ARG_PREFIX,
  buildUiLanguageAdditionalArguments,
  readInitialUiLanguageFromArgv,
} = require('../electron/ui_language_bootstrap.js');

test('uiLanguage bootstrap: builds BrowserWindow additionalArguments', () => {
  assert.deepEqual(buildUiLanguageAdditionalArguments('en'), [`${UI_LANGUAGE_ARG_PREFIX}en`]);
  assert.deepEqual(buildUiLanguageAdditionalArguments('ja'), [`${UI_LANGUAGE_ARG_PREFIX}ja`]);
});

test('uiLanguage bootstrap: rejects missing or invalid language before window creation', () => {
  assert.throws(() => buildUiLanguageAdditionalArguments(null), /UI language is required/);
  assert.throws(() => buildUiLanguageAdditionalArguments('fr'), /UI language is required/);
});

test('uiLanguage bootstrap: reads initial language from preload argv', () => {
  assert.equal(readInitialUiLanguageFromArgv(['electron', `${UI_LANGUAGE_ARG_PREFIX}ja`]), 'ja');
  assert.equal(readInitialUiLanguageFromArgv(['electron', `${UI_LANGUAGE_ARG_PREFIX}fr`]), null);
  assert.equal(readInitialUiLanguageFromArgv(['electron']), null);
});
