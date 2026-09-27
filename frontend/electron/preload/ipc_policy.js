const {
  assertValidInvokeChannel,
  isValidReceiveChannel,
  isValidSendChannel,
} = require('../src/ipc/bridge');

function createIpcPolicy() {
  return {
    assertValidInvokeChannel,
    isValidReceiveChannel,
    isValidSendChannel,
  };
}

module.exports = { createIpcPolicy };
