import { randomUUID } from 'node:crypto';
import fs from 'node:fs';
import type { safeStorage } from 'electron';
import { z } from 'zod';

export type CredentialEncryption = Pick<
  typeof safeStorage,
  'isEncryptionAvailable' | 'encryptString' | 'decryptString'
>;

const ERROR_MESSAGES = {
  encryption_unavailable: 'safeStorage encryption is unavailable on this system.',
  read_failed: 'Could not read the stored credential.',
  invalid_data: 'The stored credential could not be decoded.',
  write_failed: 'Could not save the credential.',
  delete_failed: 'Could not delete the stored credential.',
} as const;

export class CredentialStorageError extends Error {
  constructor(readonly code: keyof typeof ERROR_MESSAGES) {
    // Native errors and JSON parser messages can contain paths or credential content.
    super(ERROR_MESSAGES[code]);
    this.name = 'CredentialStorageError';
  }
}

const Envelope = z.object({ v: z.literal(1), ciphertext_b64: z.string().min(1) }).strict();

/** Main is the single writer. The caller owns validation of the decrypted JSON schema. */
export function createEncryptedJsonFile(storagePath: string, encryption: CredentialEncryption) {
  function requireEncryption(): void {
    let available: boolean;
    try {
      available = encryption.isEncryptionAvailable();
    } catch {
      throw new CredentialStorageError('encryption_unavailable');
    }
    if (!available) throw new CredentialStorageError('encryption_unavailable');
  }

  function read(): unknown {
    let raw: string;
    try {
      raw = fs.readFileSync(storagePath, 'utf8');
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === 'ENOENT') return null;
      throw new CredentialStorageError('read_failed');
    }
    requireEncryption();
    try {
      const envelope = Envelope.parse(JSON.parse(raw));
      const value: unknown = JSON.parse(
        encryption.decryptString(Buffer.from(envelope.ciphertext_b64, 'base64'))
      );
      // null is reserved for a missing file, never an existing but invalid document.
      if (value === null) throw new CredentialStorageError('invalid_data');
      return value;
    } catch {
      throw new CredentialStorageError('invalid_data');
    }
  }

  function write(value: object): void {
    requireEncryption();
    const temporaryPath = `${storagePath}.${randomUUID()}.tmp`;
    try {
      try {
        const cipher = encryption.encryptString(JSON.stringify(value));
        const envelope = JSON.stringify({ v: 1, ciphertext_b64: cipher.toString('base64') });
        // Flush the new ciphertext before replacing the old file; never truncate a saved key.
        fs.writeFileSync(temporaryPath, envelope, { flag: 'wx', mode: 0o600, flush: true });
        fs.renameSync(temporaryPath, storagePath);
      } finally {
        fs.rmSync(temporaryPath, { force: true });
      }
    } catch {
      throw new CredentialStorageError('write_failed');
    }
  }

  function remove(): void {
    try {
      fs.unlinkSync(storagePath);
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== 'ENOENT') {
        throw new CredentialStorageError('delete_failed');
      }
    }
  }

  return { read, write, remove };
}
