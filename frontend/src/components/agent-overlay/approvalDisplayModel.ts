import type { MessageKey } from '@/i18n/types';
import { formatBytes } from '@/lib/formatBytes';
import type { ActionApprovalBlocker } from '../../../electron/src/actions/actionLiveCore';

export type ApprovalDetail = {
  labelKey: MessageKey;
  value: string;
};

export type ApprovalDecision = 'approved_once' | 'approved_for_conversation' | 'denied';

export type ApprovalOutsideWorkspace = {
  folderPath: string;
  folderDisplayName: string;
  canAllowForConversation: boolean;
};

export type ApprovalDisplay = {
  operationKey: MessageKey;
  operationVars?: Record<string, string>;
  primaryLabelKey: MessageKey;
  primaryValue: string;
  details: ApprovalDetail[];
  outsideWorkspace: ApprovalOutsideWorkspace | null;
  // A decision without a label is not offered for this approval.
  decisionLabelKeys: Partial<Record<ApprovalDecision, MessageKey>>;
};

type ToolApprovalDisplay = Pick<
  ApprovalDisplay,
  'operationKey' | 'primaryLabelKey' | 'primaryValue' | 'details'
>;

export type ApprovalDisplayTranslator = (
  key: MessageKey,
  vars?: Record<string, string | number>
) => string;

function readStringValue(record: Record<string, unknown>, key: string): string | null {
  const value = record[key];
  return typeof value === 'string' && value.trim() ? value : null;
}

function readNumberValue(record: Record<string, unknown>, key: string): number | null {
  const value = record[key];
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function readStringArrayValue(record: Record<string, unknown>, key: string): string[] {
  const value = record[key];
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is string => typeof item === 'string' && item.trim().length > 0);
}

function buildGenericPrimaryValue(summary: Record<string, unknown>): string {
  return Object.entries(summary)
    .filter(([, value]) => value !== null && value !== undefined)
    .map(([key, value]) => `${key}: ${typeof value === 'string' ? value : JSON.stringify(value)}`)
    .join('\n');
}

// Any tool that would act outside the registered workspace carries this key, so
// the panel keys on it rather than on the tool.
function readOutsideWorkspace(summary: Record<string, unknown>): ApprovalOutsideWorkspace | null {
  const value = summary.outside_workspace;
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return null;
  const record = value as Record<string, unknown>;
  const folderPath = readStringValue(record, 'folder_path');
  const folderDisplayName = readStringValue(record, 'folder_display_name');
  return folderPath && folderDisplayName
    ? {
        folderPath,
        folderDisplayName,
        canAllowForConversation: record.can_allow_for_conversation === true,
      }
    : null;
}

export function buildApprovalDisplay(
  approvalPanel: ActionApprovalBlocker,
  t: ApprovalDisplayTranslator
): ApprovalDisplay {
  const toolDisplay = buildToolApprovalDisplay(approvalPanel, t);
  const outsideWorkspace = readOutsideWorkspace(approvalPanel.commandSummary);
  if (!outsideWorkspace) {
    return {
      ...toolDisplay,
      outsideWorkspace: null,
      decisionLabelKeys: {
        approved_once: 'overlay.approvalRequired.approveOnce',
        denied: 'overlay.approvalRequired.deny',
      },
    };
  }
  return {
    ...toolDisplay,
    operationKey: 'overlay.approvalRequired.outsideWorkspace.operation',
    operationVars: { folder: outsideWorkspace.folderDisplayName },
    outsideWorkspace,
    decisionLabelKeys: {
      approved_once: 'overlay.approvalRequired.outsideWorkspace.approveOnce',
      denied: 'overlay.approvalRequired.outsideWorkspace.deny',
      ...(outsideWorkspace.canAllowForConversation
        ? {
            approved_for_conversation:
              'overlay.approvalRequired.outsideWorkspace.approveForConversation',
          }
        : {}),
    },
  };
}

function buildToolApprovalDisplay(
  approvalPanel: ActionApprovalBlocker,
  t: ApprovalDisplayTranslator
): ToolApprovalDisplay {
  const summary = approvalPanel.commandSummary;
  const summaryKind = readStringValue(summary, 'summary_kind');
  const cwd = readStringValue(summary, 'cwd');

  if (approvalPanel.toolId === 'bash' || summaryKind === 'bash') {
    return {
      operationKey:
        summary.use_login_environment === true
          ? 'overlay.approvalRequired.operation.bashLoginEnvironment'
          : 'overlay.approvalRequired.operation.bash',
      primaryLabelKey: 'overlay.approvalRequired.command',
      primaryValue:
        readStringValue(summary, 'command') ?? t('overlay.approvalRequired.unavailable'),
      details: [
        ...(cwd ? [{ labelKey: 'overlay.approvalRequired.cwd' as MessageKey, value: cwd }] : []),
      ],
    };
  }

  if (approvalPanel.toolId === 'run_python' || summaryKind === 'run_python') {
    const codeSizeBytes = readNumberValue(summary, 'code_size_bytes');
    const argsCount = readNumberValue(summary, 'args_count');
    return {
      operationKey: 'overlay.approvalRequired.operation.runPython',
      primaryLabelKey: 'overlay.approvalRequired.pythonCode',
      primaryValue: t('overlay.approvalRequired.pythonCodeDescription'),
      details: [
        ...(cwd ? [{ labelKey: 'overlay.approvalRequired.cwd' as MessageKey, value: cwd }] : []),
        ...(codeSizeBytes !== null
          ? [
              {
                labelKey: 'overlay.approvalRequired.size' as MessageKey,
                value: formatBytes(codeSizeBytes),
              },
            ]
          : []),
        ...(argsCount !== null
          ? [
              {
                labelKey: 'overlay.approvalRequired.arguments' as MessageKey,
                value: String(argsCount),
              },
            ]
          : []),
      ],
    };
  }

  if (approvalPanel.toolId === 'apply_patch' || summaryKind === 'apply_patch') {
    const targetPaths = readStringArrayValue(summary, 'target_paths');
    return {
      operationKey: 'overlay.approvalRequired.operation.applyPatch',
      primaryLabelKey: 'overlay.approvalRequired.files',
      primaryValue: targetPaths.length
        ? targetPaths.join('\n')
        : t('overlay.approvalRequired.unavailable'),
      details: [],
    };
  }

  // The capture is of whatever is frontmost at the moment it happens, which only
  // Electron knows, so the request carries no target to show: naming the act is the
  // whole disclosure, and the generic line would hide it behind "this operation".
  if (approvalPanel.toolId === 'capture_screen' || summaryKind === 'screen_capture') {
    return {
      operationKey: 'overlay.approvalRequired.operation.captureScreen',
      primaryLabelKey: 'overlay.approvalRequired.details',
      primaryValue: '',
      details: [],
    };
  }

  return {
    operationKey: 'overlay.approvalRequired.operation.generic',
    primaryLabelKey: 'overlay.approvalRequired.details',
    primaryValue: buildGenericPrimaryValue(summary),
    details: [],
  };
}
