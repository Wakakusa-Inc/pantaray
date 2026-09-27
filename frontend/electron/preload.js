const { contextBridge, ipcRenderer } = require('electron');
const { readInitialUiLanguageFromArgv } = require('./ui_language_bootstrap');
const { installOverlayInteractionRecorder } = require('./preload_overlay_interaction');
const { createPreloadApi } = require('./preload/create_preload_api');
const { installDomBootstrap } = require('./preload/dom_bootstrap');
const { createIpcPolicy } = require('./preload/ipc_policy');
const { createPreloadLogger } = require('./preload/logging');
const { isNotificationWindow } = require('./preload/orchestration_api');

const logger = createPreloadLogger({ processRef: process, consoleRef: console });
logger.disableReleaseConsole();

const ipcPolicy = createIpcPolicy();
const initialUiLanguage = readInitialUiLanguageFromArgv(process.argv);
const apiParams = {
  initialUiLanguage,
  ipcPolicy,
  ipcRenderer,
  logError: logger.logError,
  processRef: process,
  windowRef: window,
};

installOverlayInteractionRecorder({
  windowRef: window,
  ipcRenderer,
  isNotificationHtmlWindow: () => isNotificationWindow(window, logger.logError),
  isValidSendChannel: ipcPolicy.isValidSendChannel,
  logError: logger.logError,
});
installDomBootstrap({ windowRef: window, documentRef: document, logError: logger.logError });

contextBridge.exposeInMainWorld('electron', createPreloadApi(apiParams));
