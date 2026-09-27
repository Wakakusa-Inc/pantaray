import { useCallback, useEffect, useRef, useState } from 'react';

import { useLocalOwner } from '@/context/localOwnerContext';

async function releaseClosedEditor(sessionId: string): Promise<void> {
  try {
    await window.electron!.privacy!.setCaptureEditing({ kind: 'end', sessionId });
  } catch {
    console.error('Failed to release the closed capture editor');
  }
}

/** Owns the recorder pause for exactly one visible editor and its pending open. */
export function useCaptureEditingSession() {
  const owner = useLocalOwner();
  const sessionRef = useRef<string | null>(null);
  const [openedSessionId, setOpenedSessionId] = useState<string | null>(null);

  useEffect(
    () => () => {
      const sessionId = sessionRef.current;
      if (sessionId === null) return;
      sessionRef.current = null;
      // Releasing this ID is valid during owner synchronization too, and main accepts
      // it only from the pause it actually granted.
      void releaseClosedEditor(sessionId);
    },
    []
  );

  const open = useCallback(async (): Promise<boolean> => {
    if (sessionRef.current !== null) return false;
    const sessionId = crypto.randomUUID();
    sessionRef.current = sessionId;
    try {
      const applied = await window.electron!.privacy!.setCaptureEditing({
        kind: 'begin',
        ownerId: owner.id,
        sessionId,
      });
      if (sessionRef.current !== sessionId) return false;
      if (!applied) throw new Error('Capture editing was not granted.');
      setOpenedSessionId(sessionId);
      return true;
    } catch (error) {
      if (sessionRef.current !== sessionId) return false;
      // IPC failure does not prove that main failed before acquiring the pause.
      await releaseClosedEditor(sessionId);
      if (sessionRef.current !== sessionId) return false;
      sessionRef.current = null;
      throw error;
    }
  }, [owner.id]);

  const close = useCallback(async (): Promise<boolean> => {
    // A caller holding an older callback names an editor this hook has already closed.
    if (openedSessionId === null || sessionRef.current !== openedSessionId) return false;
    await window.electron!.privacy!.setCaptureEditing({ kind: 'end', sessionId: openedSessionId });
    if (sessionRef.current !== openedSessionId) return false;
    sessionRef.current = null;
    setOpenedSessionId(null);
    return true;
  }, [openedSessionId]);

  return { isOpen: openedSessionId !== null, open, close };
}
