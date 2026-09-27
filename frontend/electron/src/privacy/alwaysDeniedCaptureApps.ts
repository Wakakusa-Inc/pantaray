/**
 * Applications a screen capture is never taken of.
 *
 * The recording filter is the user's to set, and everywhere else the user's setting
 * wins. Password managers are the exception: a capture taken while one is frontmost
 * can hand a decrypted vault to a model and, from there, to a provider. That loss is
 * not recoverable by changing a setting afterwards, so this list outranks the filter
 * - an app here is refused even when the user's "only these apps" list names it.
 *
 * Matching is exact on the bundle identifier, and case-insensitively exact on the
 * display name for the rare bundle that reports no identifier. Prefix matching is
 * deliberately avoided: it would silently cover unrelated apps from the same vendor.
 */

const ALWAYS_DENIED_BUNDLE_IDS: readonly string[] = [
  'com.1password.1password',
  'com.1password.1password7',
  'com.agilebits.onepassword',
  'com.agilebits.onepassword4',
  'com.agilebits.onepassword7',
  'com.apple.keychainaccess',
  'com.apple.Passwords',
  'com.bitwarden.desktop',
  'com.dashlane.dashlanephonefinal',
  'com.dashlane.Dashlane',
  'com.keepassxc.keepassxc',
  'com.lastpass.LastPass',
  'com.nordpass.macos',
  'com.proton.pass.electron',
  'in.sinew.Enpass-Desktop',
  'org.keepassx.keepassxc',
];

const ALWAYS_DENIED_APP_NAMES: readonly string[] = [
  '1password',
  'bitwarden',
  'dashlane',
  'enpass',
  'keychain access',
  'keepassxc',
  'lastpass',
  'nordpass',
  'passwords',
  'proton pass',
];

const DENIED_BUNDLE_IDS = new Set(ALWAYS_DENIED_BUNDLE_IDS);
const DENIED_APP_NAMES = new Set(ALWAYS_DENIED_APP_NAMES);

export function isAlwaysDeniedCaptureApp(app: { name: string; bundleId: string | null }): boolean {
  if (app.bundleId !== null && DENIED_BUNDLE_IDS.has(app.bundleId)) return true;
  return DENIED_APP_NAMES.has(app.name.trim().toLowerCase());
}

export { ALWAYS_DENIED_APP_NAMES, ALWAYS_DENIED_BUNDLE_IDS };
