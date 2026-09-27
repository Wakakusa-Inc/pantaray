import { useCallback, useEffect, useRef, useState } from 'react';

import type { MessageKey } from '@/i18n/types';

export type ActionApprovalMode = 'prompt_each_time' | 'always_allow';
export type ActionApprovalModeControl = ReturnType<typeof useActionApprovalMode>;

type State = {
  scopeId: string | null;
  mode: ActionApprovalMode | null;
  errorKey: MessageKey | null;
  isSaving: boolean;
};

const EMPTY_STATE: Omit<State, 'scopeId'> = {
  mode: null,
  errorKey: null,
  isSaving: false,
};

function readEffectiveMode(actionId: string | null): (() => Promise<ActionApprovalMode>) | null {
  if (actionId === null) {
    const readDefault = window.electron?.approval?.getWorkspaceEditCommandPreference;
    return readDefault ? async () => (await readDefault()).approval_mode : null;
  }
  const readAction = window.electron?.agentOverlay?.getActionApprovalMode;
  return readAction ? async () => (await readAction(actionId)).approval_mode : null;
}

/** Draft consent travels with the first submission; existing consent is saved per Action. */
export function useActionApprovalMode(actionId: string | null, suggestionId: string | null) {
  const scopeId = actionId ?? suggestionId;
  const [state, setState] = useState<State>({ scopeId: null, ...EMPTY_STATE });
  const [resetVersion, setResetVersion] = useState(0);
  const generationRef = useRef(0);
  const current = state.scopeId === scopeId ? state : { scopeId, ...EMPTY_STATE };

  const reset = useCallback(() => {
    // Account changes can replace a draft while both Action identities are null.
    generationRef.current += 1;
    setState({ scopeId: null, ...EMPTY_STATE });
    setResetVersion((version) => version + 1);
  }, []);

  useEffect(() => {
    const generation = ++generationRef.current;
    const read = readEffectiveMode(actionId);
    if (read) {
      void read()
        .then((mode) => {
          if (generation !== generationRef.current) return;
          setState({ scopeId, mode, errorKey: null, isSaving: false });
        })
        .catch(() => {
          if (generation !== generationRef.current) return;
          setState({ scopeId, ...EMPTY_STATE, errorKey: 'overlay.approvalMode.loadFailed' });
        });
    }
    return () => {
      generationRef.current += 1;
    };
  }, [actionId, scopeId, resetVersion]);

  const selectMode = useCallback(
    async (nextMode: ActionApprovalMode) => {
      if (actionId === null) {
        setState({ scopeId, mode: nextMode, errorKey: null, isSaving: false });
        return;
      }
      const write = window.electron?.agentOverlay?.setActionApprovalMode;
      if (!write) return;
      const generation = generationRef.current;
      setState((current) => ({ ...current, isSaving: true, errorKey: null }));
      try {
        const response = await write({ actionId, approvalMode: nextMode });
        if (generation !== generationRef.current) return;
        setState({ scopeId, mode: response.approval_mode, errorKey: null, isSaving: false });
      } catch {
        if (generation !== generationRef.current) return;
        setState({ scopeId, ...EMPTY_STATE, errorKey: 'overlay.approvalMode.saveFailed' });
      }
    },
    [actionId, scopeId]
  );

  return {
    mode: current.mode,
    errorKey: current.errorKey,
    isSaving: current.isSaving,
    selectMode,
    reset,
  };
}
