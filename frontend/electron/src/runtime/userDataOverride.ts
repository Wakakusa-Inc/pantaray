import fs from 'fs';
import path from 'path';

export const DEV_USER_DATA_DIR_ENV = 'PANTARAY_USER_DATA_DIR';

type UserDataPathApp = {
  isPackaged: boolean;
  setPath: (name: 'userData', value: string) => void;
};

export function applyDevUserDataDirOverride(params: {
  app: UserDataPathApp;
  env?: NodeJS.ProcessEnv;
}): string | null {
  const env = params.env ?? process.env;
  const rawDir = String(env[DEV_USER_DATA_DIR_ENV] ?? '').trim();
  if (!rawDir) {
    return null;
  }
  if (params.app.isPackaged) {
    return null;
  }
  if (!path.isAbsolute(rawDir)) {
    throw new Error(`${DEV_USER_DATA_DIR_ENV} must be an absolute path.`);
  }
  fs.mkdirSync(rawDir, { recursive: true, mode: 0o700 });
  params.app.setPath('userData', rawDir);
  return rawDir;
}
