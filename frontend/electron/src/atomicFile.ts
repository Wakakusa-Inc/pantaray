import fs from 'node:fs';
import path from 'node:path';
import { randomUUID } from 'node:crypto';

/** The caller supplies a temporary directory on the target's filesystem for atomic rename. */
export function writeFileAtomic(
  targetPath: string,
  tempDirectoryPath: string,
  payload: Buffer
): void {
  fs.mkdirSync(path.dirname(targetPath), { recursive: true });
  fs.mkdirSync(tempDirectoryPath, { recursive: true });
  const tempPath = path.join(tempDirectoryPath, `${path.basename(targetPath)}.tmp-${randomUUID()}`);
  try {
    const fd = fs.openSync(tempPath, 'wx', 0o600);
    try {
      fs.writeFileSync(fd, payload);
      fs.fsyncSync(fd);
    } finally {
      fs.closeSync(fd);
    }
    fs.renameSync(tempPath, targetPath);
  } finally {
    fs.rmSync(tempPath, { force: true });
  }
}
