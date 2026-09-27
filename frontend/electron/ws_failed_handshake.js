function summarizeCleanupError(err) {
  return {
    name: err instanceof Error ? err.name : 'UnknownError',
    message: err instanceof Error ? err.message : String(err),
  };
}

function closeFailedHandshake(req, res) {
  const errors = [];
  let responseResumed = false;
  let requestAborted = false;
  let socketDestroyed = false;

  try {
    if (typeof res?.resume === 'function') {
      res.resume();
      responseResumed = true;
    }
  } catch (err) {
    errors.push({ operation: 'response_resume', ...summarizeCleanupError(err) });
  }

  try {
    if (typeof req?.abort === 'function') {
      req.abort();
      requestAborted = true;
    } else if (typeof req?.destroy === 'function') {
      req.destroy();
      requestAborted = true;
    }
  } catch (err) {
    errors.push({ operation: 'request_abort', ...summarizeCleanupError(err) });
  }

  try {
    const socket = req?.socket;
    if (socket && !socket.destroyed && typeof socket.destroy === 'function') {
      socket.destroy();
      socketDestroyed = true;
    }
  } catch (err) {
    errors.push({ operation: 'socket_destroy', ...summarizeCleanupError(err) });
  }

  return {
    responseResumed,
    requestAborted,
    socketDestroyed,
    errors,
  };
}

module.exports = { closeFailedHandshake };
