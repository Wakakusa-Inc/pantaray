import type { MainContext } from '../context';

export async function runAuditedMutation<T>(
  ctx: MainContext,
  operation: string,
  mutation: () => T | Promise<T>,
  /** Which results the audit records as failed; `false` unless the caller says otherwise. */
  failed: (result: T) => boolean = (result) => result === false
): Promise<T> {
  try {
    const result = await mutation();
    ctx.security.auditMutation(operation, failed(result) ? 'failed' : 'succeeded');
    return result;
  } catch (error) {
    ctx.security.auditMutation(operation, 'failed');
    throw error;
  }
}
