import type { App } from 'electron';

type AppWithQuitFlag = App & {
  isQuitting?: boolean;
};

export function markUpdateInstallQuitRequested(app: App): void {
  (app as AppWithQuitFlag).isQuitting = true;
}
