const { BrowserWindow, systemPreferences } = require('electron');

/**
 * 最前面アプリのアプリ名とウィンドウタイトルを取得する。
 * ウィンドウタイトルは Slack のワークスペース判定などに使う。
 * @returns {Promise<{ name: string, title: string }>}
 */
async function captureActiveWindowInfo(execPromise, mainWindow, notificationWindow) {
  let activeWindowInfo;
  try {
    const focusedWindow = BrowserWindow.getFocusedWindow();
    if (focusedWindow && focusedWindow !== mainWindow && focusedWindow !== notificationWindow) {
      const windowTitle = focusedWindow.getTitle();
      activeWindowInfo = {
        name: 'Active Application',
        title: windowTitle,
      };
    } else {
      if (process.platform === 'darwin' && !systemPreferences.isTrustedAccessibilityClient(false)) {
        return {
          name: 'Unknown App (Permission Required)',
          title: 'Unknown Window',
        };
      }
      try {
        // AppleScript でアプリ名 + 最前面ウィンドウのタイトルを取得
        const script = `
          tell application "System Events"
            set frontApp to first application process whose frontmost is true
            set appName to name of frontApp
            set winTitle to ""
            set axTitle to ""
            try
              set winTitle to name of front window of frontApp
            end try
            -- Slack 等で "name" が短い/空になるケースがあるため AXTitle をフォールバックする
            try
              set axTitle to value of attribute "AXTitle" of front window of frontApp
            end try
            if axTitle is not "" then
              if winTitle is "" then
                set winTitle to axTitle
              else if (length of axTitle) is greater than (length of winTitle) then
                set winTitle to axTitle
              end if
            end if
            return appName & "\\t" & winTitle
          end tell
        `;
        const { stdout } = await execPromise(`osascript -e '${script.replace(/'/g, "'\\''")}'`);
        const parts = String(stdout || '').split('\t');
        const appName = (parts[0] || '').trim();
        const winTitle = (parts[1] || '').trim() || appName;
        activeWindowInfo = { name: appName || 'Unknown App', title: winTitle };
      } catch {
        activeWindowInfo = {
          name: 'Unknown App (Permission Required)',
          title: 'Unknown Window',
        };
      }
    }
  } catch {
    activeWindowInfo = { name: 'Unknown App', title: 'Unknown Window' };
  }
  return activeWindowInfo;
}

/**
 * アクティブなブラウザタブのURLを AppleScript で取得する。
 * - Chrome: active tab of front window
 * - Safari: current tab of front window
 *
 * 取得できない場合は url=null とし、理由を error に入れて返す。
 *
 * @param {(cmd: string) => Promise<{stdout: string}>} execPromise
 * @param {string | null | undefined} activeAppName
 * @returns {Promise<{url: string | null, appName: string | null, windowName: string | null, error: string | null}>}
 */
async function getActiveBrowserUrl(execPromise, activeAppName) {

  const normalize = (s) => String(s || '').trim();
  const hintedAppName = normalize(activeAppName);

  async function tryChrome(chromeAppName) {
    const cmd = buildBrowserWindowProbeCommand(chromeAppName);
    const { stdout, stderr } = await execPromise(cmd);
    return { ...parseBrowserWindowProbeOutput(stdout), stderr: normalize(stderr) || null };
  }

  async function trySafari() {
    const cmd = buildBrowserWindowProbeCommand('Safari');
    const { stdout, stderr } = await execPromise(cmd);
    return { ...parseBrowserWindowProbeOutput(stdout), stderr: normalize(stderr) || null };
  }

  // まずは frontmost アプリ名を取得（失敗しても hintedAppName を使って試す）
  let frontAppName = null;
  let frontAppErr = null;
  try {
    const { stdout, stderr } = await execPromise(
      'osascript -e \'tell application "System Events" to get name of first application process whose frontmost is true\''
    );
    frontAppName = normalize(stdout) || null;
    if (!frontAppName && normalize(stderr)) {
      frontAppErr = normalize(stderr);
    }
  } catch (e) {
    frontAppErr = normalize(e && e.stderr ? e.stderr : e && e.message ? e.message : e);
  }

  const appName = frontAppName || hintedAppName || null;
  const isChromeLike =
    appName === 'Google Chrome' ||
    appName === 'Google Chrome Canary' ||
    appName === 'Google Chrome Beta' ||
    appName === 'Google Chrome Dev' ||
    appName === 'Chromium';
  const isSafari = appName === 'Safari';

  // 1) frontmost / hinted が Chrome/Safari なら、それを優先して取得（意図に忠実）
  if (isChromeLike) {
    try {
      const res = await tryChrome(appName);
      if (res.url && res.windowName) {
        return { url: res.url, appName, windowName: res.windowName, error: null };
      }
      return {
        url: res.url,
        appName,
        windowName: res.windowName,
        error: res.stderr || 'Chrome returned an empty URL or window name.',
      };
    } catch (e) {
      const err = normalize(e && e.stderr ? e.stderr : e && e.message ? e.message : e);
      return { url: null, appName, windowName: null, error: err || 'AppleScript failed (Chrome).' };
    }
  }
  if (isSafari) {
    try {
      const res = await trySafari();
      if (res.url && res.windowName) {
        return { url: res.url, appName, windowName: res.windowName, error: null };
      }
      return {
        url: res.url,
        appName,
        windowName: res.windowName,
        error: res.stderr || 'Safari returned an empty URL or window name.',
      };
    } catch (e) {
      const err = normalize(e && e.stderr ? e.stderr : e && e.message ? e.message : e);
      return { url: null, appName, windowName: null, error: err || 'AppleScript failed (Safari).' };
    }
  }

  // 2) ここまで来たら「前面判定できない/前面が別アプリ」。
  // UI 用途ではユーザー負担を減らすため、Chrome/Safari を順に取得してみる（裏でもOK）。
  const candidates = ['Google Chrome', 'Safari'];
  const errors = [];
  for (const cand of candidates) {
    try {
      if (cand === 'Safari') {
        const res = await trySafari();
        if (res.url && res.windowName) {
          return { url: res.url, appName: 'Safari', windowName: res.windowName, error: null };
        }
        errors.push(`Safari: ${res.stderr || 'empty URL or window name'}`);
      } else {
        const res = await tryChrome(cand);
        if (res.url && res.windowName) {
          return { url: res.url, appName: cand, windowName: res.windowName, error: null };
        }
        errors.push(`Chrome: ${res.stderr || 'empty URL or window name'}`);
      }
    } catch (e) {
      const err = normalize(e && e.stderr ? e.stderr : e && e.message ? e.message : e);
      errors.push(`${cand}: ${err || 'AppleScript failed'}`);
    }
  }

  const frontHint = appName ? `Frontmost: ${appName}` : null;
  const base = frontAppErr ? `System Events: ${frontAppErr}` : null;
  const detail = errors.length ? `Tried: ${errors.join(' | ')}` : null;
  return {
    url: null,
    appName: appName || null,
    windowName: null,
    error:
      [frontHint, base, detail].filter(Boolean).join(' / ') ||
      'Could not get URL from Chrome or Safari.',
  };
}

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
 * `captureActiveWindowInfo` は UI 表示用で、判定できない場合も
 * "Unknown App (Permission Required)" のような表示文字列を返す。撮影可否の判定に
 * それを使うと「判定できなかった」を「そういう名前のアプリ」として扱ってしまうため、
 * ここでは取得できなければ null を返し、呼び手が fail-closed に倒せるようにする。
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
  captureActiveWindowInfo,
  getActiveBrowserUrl,
  probeBrowserUrlForApp,
  readFrontmostApplication,
};
