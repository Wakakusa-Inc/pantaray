function installOverlayInteractionRecorder(params) {
  const {
    windowRef,
    ipcRenderer,
    isNotificationHtmlWindow,
    isValidSendChannel,
    logError,
  } = params;
  if (!isNotificationHtmlWindow()) return;
  try {
    windowRef.addEventListener(
      'pointerdown',
      () => {
        if (isValidSendChannel('overlay:recordInteraction')) {
          ipcRenderer.send('overlay:recordInteraction');
        }
      },
      { capture: true }
    );
  } catch (err) {
    logError('installOverlayInteractionRecorder failed', err);
  }
}

module.exports = {
  installOverlayInteractionRecorder,
};
