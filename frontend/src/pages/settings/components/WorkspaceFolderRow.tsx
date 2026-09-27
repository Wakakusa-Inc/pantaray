import { Trash2 } from 'lucide-react';

import type { Translate } from '../types';
import {
  splitPathForMiddleEllipsis,
  type FocusKey,
  type WorkspaceFolder,
} from './workspaceSettingsModel';

interface WorkspaceFolderRowProps {
  busy: boolean;
  deleteButtonId: FocusKey;
  folder: WorkspaceFolder;
  t: Translate;
  onDelete: (folderId: string) => Promise<void>;
}

export function WorkspaceFolderRow(props: WorkspaceFolderRowProps) {
  const [pathStart, pathEnd] = splitPathForMiddleEllipsis(props.folder.real_path);
  return (
    <div className="workspace-folder-row">
      <div className="workspace-folder-row-header">
        <span className="workspace-folder-name">{props.folder.display_name}</span>
        <button
          type="button"
          id={props.deleteButtonId}
          className="workspace-icon-button"
          aria-label={`${props.t('common.delete')} ${props.folder.display_name}`}
          aria-busy={props.busy}
          title={props.t('common.delete')}
          onClick={() => void props.onDelete(props.folder.folder_id)}
        >
          <Trash2 size={14} aria-hidden="true" />
        </button>
      </div>
      <span
        className="workspace-folder-path"
        aria-label={props.folder.real_path}
        title={props.folder.real_path}
      >
        <span className="workspace-folder-path-start">{pathStart}</span>
        <span className="workspace-folder-path-end">{pathEnd}</span>
      </span>
    </div>
  );
}
