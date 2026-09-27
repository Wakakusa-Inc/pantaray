const UI_LANGUAGE_ARG_PREFIX = '--pantaray-ui-language=';

function isUiLanguage(value) {
  return value === 'en' || value === 'ja';
}

function buildUiLanguageAdditionalArguments(language) {
  if (!isUiLanguage(language)) {
    throw new Error('UI language is required before creating a renderer window.');
  }
  return [`${UI_LANGUAGE_ARG_PREFIX}${language}`];
}

function readInitialUiLanguageFromArgv(argv) {
  const args = Array.isArray(argv) ? argv : [];
  const arg = args.find((item) => String(item || '').startsWith(UI_LANGUAGE_ARG_PREFIX));
  if (!arg) return null;
  const value = String(arg).slice(UI_LANGUAGE_ARG_PREFIX.length);
  return isUiLanguage(value) ? value : null;
}

module.exports = {
  UI_LANGUAGE_ARG_PREFIX,
  buildUiLanguageAdditionalArguments,
  readInitialUiLanguageFromArgv,
};
