import { useEffect, useLayoutEffect, useRef } from 'react';
import type { RefObject } from 'react';
import { createPortal } from 'react-dom';
import styled, { css } from 'styled-components';
import { Plus } from 'lucide-react';

import { useI18n } from '@/context/useI18n';
import { mentionOptionId, type ComposerMention } from './composerMentions';

const OPTION_HEIGHT_PX = 28;
const VISIBLE_OPTIONS = 8;
const FLOATING_PADDING_PX = 4;
const FLOATING_GAP_PX = 6;

/** Room a full floating list needs above the composer frame: rows, padding, border, gap. */
export const MENTION_PANEL_ROOM_PX =
  OPTION_HEIGHT_PX * VISIBLE_OPTIONS + FLOATING_PADDING_PX * 2 + 2 + FLOATING_GAP_PX;

export type MentionPlacement = 'above' | 'below';

/**
 * `above` floats over the conversation, portalled with fixed positioning like the approval mode
 * menu so no ancestor clips it. `below` sits in flow; the window grows downward, composer fixed.
 */
const MentionPanel = styled.div<{ $placement: MentionPlacement }>`
  display: grid;
  gap: 4px;

  ${({ $placement }) =>
    $placement === 'above'
      ? css`
          position: fixed;
          z-index: 1000;
          box-sizing: border-box;
          padding: ${FLOATING_PADDING_PX}px;
          border: 1px solid var(--border-color);
          border-radius: 12px;
          /* Opaque so the conversation underneath does not show through. */
          background: rgb(26, 30, 36);
          box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4);
          font-size: var(--text-body-size);
          -webkit-app-region: no-drag;
        `
      : css`
          padding-top: 8px;
          border-top: 1px solid var(--border-color);
        `}
`;

const MentionListbox = styled.ul`
  max-height: ${OPTION_HEIGHT_PX * VISIBLE_OPTIONS}px;
  margin: 0;
  padding: 0;
  overflow-y: auto;
  list-style: none;
`;

const MentionOption = styled.li`
  display: flex;
  align-items: center;
  gap: 6px;
  box-sizing: border-box;
  height: ${OPTION_HEIGHT_PX}px;
  padding: 0 8px;
  border-radius: 8px;
  color: var(--text-primary);
  cursor: pointer;

  span {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  svg {
    flex: none;
    width: 14px;
    height: 14px;
  }

  &:hover,
  &[aria-selected='true'] {
    background: rgba(255, 255, 255, 0.1);
  }
`;

const MentionFailure = styled.p`
  margin: 0;
  padding: 0 8px;
  color: rgba(254, 202, 202, 0.95);
  font-size: var(--text-meta-size);
`;

export type MentionOptionItem =
  | (Readonly<{ kind: 'project' }> & Omit<ComposerMention, 'start' | 'end'>)
  | Readonly<{ kind: 'add' }>;

export function ProjectMentionList({
  id,
  placement,
  anchorRef,
  options,
  activeIndex,
  loadFailed,
  onPick,
}: {
  id: string;
  placement: MentionPlacement;
  /** The composer text field; the floating list aligns with its form's frame. */
  anchorRef: RefObject<HTMLTextAreaElement>;
  options: readonly MentionOptionItem[];
  activeIndex: number;
  loadFailed: boolean;
  onPick: (index: number) => void;
}) {
  const { t } = useI18n();
  const panelRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    document.getElementById(mentionOptionId(id, activeIndex))?.scrollIntoView({ block: 'nearest' });
  }, [id, activeIndex]);
  useLayoutEffect(() => {
    if (placement !== 'above') return;
    const place = () => {
      const frame = anchorRef.current?.form?.getBoundingClientRect();
      const panel = panelRef.current;
      if (!frame || !panel) return;
      panel.style.left = `${frame.left}px`;
      panel.style.width = `${frame.width}px`;
      panel.style.bottom = `${window.innerHeight - frame.top + FLOATING_GAP_PX}px`;
    };
    place();
    window.addEventListener('resize', place);
    return () => window.removeEventListener('resize', place);
  });

  const panel = (
    // Keep focus (and the caret) in the text field while the pointer picks an option.
    <MentionPanel
      ref={panelRef}
      $placement={placement}
      onMouseDown={(event) => event.preventDefault()}
    >
      {loadFailed ? (
        <MentionFailure role="alert">{t('overlay.composer.mention.loadFailed')}</MentionFailure>
      ) : null}
      <MentionListbox id={id} role="listbox" aria-label={t('overlay.composer.mention.label')}>
        {options.map((option, index) => (
          <MentionOption
            key={option.kind === 'project' ? option.projectId : 'add'}
            id={mentionOptionId(id, index)}
            role="option"
            aria-selected={index === activeIndex}
            onClick={() => onPick(index)}
          >
            {option.kind === 'add' ? <Plus strokeWidth={1.75} aria-hidden /> : null}
            <span>
              {option.kind === 'project'
                ? option.displayName
                : t('overlay.composer.mention.addProject')}
            </span>
          </MentionOption>
        ))}
      </MentionListbox>
    </MentionPanel>
  );
  return placement === 'above' ? createPortal(panel, document.body) : panel;
}
