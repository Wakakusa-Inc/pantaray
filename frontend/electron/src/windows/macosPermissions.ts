import { app, shell, systemPreferences } from 'electron';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import type { CapturePermission } from '../context/zaneiProcess';

const run = promisify(execFile);

type SecurityPane = 'Privacy_Accessibility' | 'Privacy_ListenEvent' | 'Privacy_Automation';

/**
 * Lets the E2E harness stand in for macOS: a CI runner grants no app Accessibility,
 * and TCC cannot be seeded. Honoured only in an unpackaged build, so a shipped app
 * reads the real permission whatever its environment says.
 */
const ASSUME_PERMISSIONS_ENV = 'PANTARAY_E2E_ASSUME_CAPTURE_PERMISSIONS';

function openSecurityPane(pane: SecurityPane): Promise<void> {
  return shell.openExternal(`x-apple.systempreferences:com.apple.preference.security?${pane}`);
}

/**
 * Whether macOS lets this app record at all.
 *
 * Everything the assistant knows comes from the recorder, and the recorder cannot
 * read a single window without Accessibility — which is also the only one of its
 * permissions macOS reports to this process. So this is the gate the whole product
 * stands behind, read live because the user grants it in System Settings, outside
 * the app. Input Monitoring and browser Automation are asked for by the recorder's
 * own start check and surface through the capture status instead.
 */
export function holdsCaptureOsPermissions(): boolean {
  if (!app.isPackaged && process.env[ASSUME_PERMISSIONS_ENV] === '1') return true;
  return process.platform === 'darwin' && systemPreferences.isTrustedAccessibilityClient(false);
}

/** Opens the pane the gate's permission lives in, for a user who has to grant it. */
export function openCapturePermissionSettings(): Promise<void> {
  return openSecurityPane('Privacy_Accessibility');
}

/** Called only by an explicit recording start. */
export async function requestCapturePermissions(missing: CapturePermission[]): Promise<void> {
  for (const [capability, bundleId] of [
    ['automate_browser', 'com.google.Chrome'],
    ['automate_safari', 'com.apple.Safari'],
  ] as const) {
    if (!missing.includes(capability)) continue;
    try {
      // Sending a harmless AppleEvent makes this browser appear in Pantaray's Automation list.
      await run('/usr/bin/osascript', ['-e', `tell application id "${bundleId}" to get name`], {
        timeout: 10_000,
      });
    } catch (error) {
      // User denial is the expected permission-required result; other failures remain visible.
      if (
        !(error instanceof Error && 'stderr' in error && String(error.stderr).includes('-1743'))
      ) {
        throw error;
      }
    }
  }
  await openSecurityPane(
    missing.includes('read_accessibility_tree')
      ? 'Privacy_Accessibility'
      : missing.includes('observe_input')
        ? 'Privacy_ListenEvent'
        : 'Privacy_Automation'
  );
}
