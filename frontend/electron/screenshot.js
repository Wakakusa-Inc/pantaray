function buildBrowserWindowProbeCommand(appName) {
  const escapedAppName = appName.replace(/"/g, '\\"');
  const urlExpression =
    appName === 'Safari' ? 'URL of current tab of targetWindow' : 'URL of active tab of targetWindow';
  const script = `
    tell application "${escapedAppName}"
      set targetWindow to front window
      return (${urlExpression}) & "\\t" & (name of targetWindow)
    end tell
  `;
  return `osascript -e '${script.replace(/'/g, "'\\''")}'`;
}

function parseBrowserWindowProbeOutput(stdout) {
  const output = String(stdout || '');
  const separatorIndex = output.indexOf('\t');
  if (separatorIndex < 0) {
    return { url: output.trim() || null, windowName: null };
  }
  return {
    url: output.slice(0, separatorIndex).trim() || null,
    windowName: output.slice(separatorIndex + 1).trim() || null,
  };
}

/**
 * 指定された前面ブラウザだけから URL を取得する。
 * capture gate 用のため、System Events での再判定や別ブラウザへの試行は行わない。
 *
 * @param {(cmd: string) => Promise<{stdout: string, stderr?: string}>} execPromise
 * @param {string | null | undefined} activeAppName
 * @returns {Promise<{url: string | null, appName: string | null, windowName: string | null, error: string | null}>}
 */
async function probeBrowserUrlForApp(execPromise, activeAppName) {


  const appName = String(activeAppName || '').trim();
  let command;
  if (appName === 'Google Chrome') {
    command = buildBrowserWindowProbeCommand(appName);
  } else if (appName === 'Safari') {
    command = buildBrowserWindowProbeCommand(appName);
  } else {
    return {
      url: null,
      appName: appName || null,
      windowName: null,
      error: 'Unsupported browser app.',
    };
  }

  try {
    const { stdout, stderr } = await execPromise(command);
    const { url, windowName } = parseBrowserWindowProbeOutput(stdout);
    const error = String(stderr || '').trim();
    return {
      url,
      appName,
      windowName,
      error: url && windowName ? null : error || `${appName} returned an empty URL or window name.`,
    };
  } catch (caught) {
    const error = String(caught?.stderr || caught?.message || caught || '').trim();
    return {
      url: null,
      appName,
      windowName: null,
      error: error || `AppleScript failed (${appName}).`,
    };
  }
}

/**
 * 撮影ゲート専用の frontmost アプリ判定。
 *
 * 「判定できなかった」を表示用の文字列（アプリ名に見える値）で返すと、撮影可否の判定が
 * それを「そういう名前のアプリ」として扱ってしまう。取得できなければ null を返し、
 * 呼び手が fail-closed に倒せるようにする。
 *
 * @param {(cmd: string) => Promise<{stdout: string}>} execPromise
 * @returns {Promise<{name: string, bundleId: string | null} | null>}
 */
async function readFrontmostApplication(execPromise) {
  const script = `
    tell application "System Events"
      set frontApp to first application process whose frontmost is true
      set appName to name of frontApp
      set appBundleId to ""
      try
        set appBundleId to bundle identifier of frontApp
      end try
      return appName & "\\t" & appBundleId
    end tell
  `;
  try {
    const { stdout } = await execPromise(`osascript -e '${script.replace(/'/g, "'\\''")}'`);
    const [rawName, rawBundleId] = String(stdout || '').split('\t');
    const name = (rawName || '').trim();
    if (!name) return null;
    return { name, bundleId: (rawBundleId || '').trim() || null };
  } catch {
    return null;
  }
}

module.exports = {
  probeBrowserUrlForApp,
  readFrontmostApplication,
};
