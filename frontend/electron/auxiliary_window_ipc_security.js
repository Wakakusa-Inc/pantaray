function createAuxiliaryWindowIpcSecurity() {
  let registration = null;

  function configure(nextRegistration) {
    if (
      !nextRegistration ||
      typeof nextRegistration.registerWindow !== 'function' ||
      typeof nextRegistration.unregisterWindow !== 'function'
    ) {
      throw new TypeError(
        'Auxiliary window IPC security requires registerWindow and unregisterWindow functions.'
      );
    }
    registration = nextRegistration;
  }

  function registerWindow(role, win) {
    if (!registration) {
      throw new Error('Auxiliary window IPC security is not configured.');
    }
    if (!win || !win.webContents || typeof win.once !== 'function') {
      throw new TypeError('Auxiliary window IPC security requires a BrowserWindow.');
    }

    const activeRegistration = registration;
    const sender = win.webContents;
    activeRegistration.registerWindow(role, sender);
    win.once('closed', () => activeRegistration.unregisterWindow(sender));
  }

  return { configure, registerWindow };
}

module.exports = { createAuxiliaryWindowIpcSecurity };
