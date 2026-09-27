/** OAuth refresh tokens stay in main; unavailable encryption never permits plaintext storage. */
import path from 'node:path';
import { z } from 'zod';
import type { ChatgptTokens } from './chatgptOauth';
import {
  createEncryptedJsonFile,
  CredentialStorageError,
  type CredentialEncryption,
} from './encryptedJsonFile';

const StoredTokens = z
  .object({
    v: z.literal(1),
    tokens: z
      .object({
        accessToken: z.string().min(1),
        refreshToken: z.string().min(1),
        accountId: z.string().min(1),
        expiresAt: z.string().datetime(),
      })
      .strict(),
  })
  .strict();

export type ChatgptTokenStoreResult =
  | { ok: true }
  | { ok: false; error: CredentialStorageError['code'] };

export type ChatgptTokenStore = {
  /** null means no saved file. Storage failures throw CredentialStorageError. */
  load: () => ChatgptTokens | null;
  save: (tokens: ChatgptTokens) => ChatgptTokenStoreResult;
  clear: () => ChatgptTokenStoreResult;
};

export function createChatgptTokenStore(params: {
  userDataDir: string;
  safeStorage: CredentialEncryption;
}): ChatgptTokenStore {
  const file = createEncryptedJsonFile(
    path.join(params.userDataDir, 'chatgpt-oauth.enc.json'),
    params.safeStorage
  );

  function mutate(operation: () => void): ChatgptTokenStoreResult {
    try {
      operation();
      return { ok: true };
    } catch (error) {
      if (!(error instanceof CredentialStorageError)) throw error;
      return { ok: false, error: error.code };
    }
  }

  return {
    load: () => {
      const value = file.read();
      if (value === null) return null;
      const parsed = StoredTokens.safeParse(value);
      if (!parsed.success) throw new CredentialStorageError('invalid_data');
      return parsed.data.tokens;
    },
    save: (tokens) => mutate(() => file.write({ v: 1, tokens })),
    clear: () => mutate(file.remove),
  };
}
