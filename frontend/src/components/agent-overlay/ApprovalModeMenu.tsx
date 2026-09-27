import { useEffect, useId, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import styled from 'styled-components';
import { Shield, ShieldCheck, Zap } from 'lucide-react';

import { useI18n } from '@/context/useI18n';
import type { ActionApprovalMode, ActionApprovalModeControl } from './useActionApprovalMode';

const MODES: readonly ActionApprovalMode[] = ['prompt_each_time', 'always_allow'];

const MODE_LABEL_KEY = {
  prompt_each_time: 'overlay.approvalMode.mode.promptEachTime',
  always_allow: 'overlay.approvalMode.mode.alwaysAllow',
} as const;

const MODE_DESCRIPTION_KEY = {
  prompt_each_time: 'overlay.approvalMode.description.promptEachTime',
  always_allow: 'overlay.approvalMode.description.alwaysAllow',
} as const;

const MODE_ICON = {
  prompt_each_time: ShieldCheck,
  always_allow: Zap,
} as const;

/** Gap between the trigger and the popover edge. */
const ANCHOR_GAP_PX = 6;
/** Keeps the popover clear of the overlay window's rounded edges. */
const VIEWPORT_MARGIN_PX = 8;

const ModeRoot = styled.div`
  display: grid;
  gap: var(--space-xs);
  justify-items: start;
`;

/**
 * いま効いている権限モードを示すトリガ。
 *
 * 枠は持たず、薄い面だけを持つピル。composer の枠の中では、押せるものと読むだけの
 * ものが同じ行に並ぶので、この面が「これは状態表示ではなく操作である」ことを示す。
 * 高さは同じ行の追加・送信と揃えて 32px。
 */
const ModeTrigger = styled.button`
  justify-self: start;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 32px;
  padding: 0 10px;
  border: 0;
  border-radius: 999px;
  color: var(--text-primary);
  background: rgba(255, 255, 255, 0.06);
  font: inherit;
  font-size: var(--text-ui-size-sm);
  line-height: 1.2;
  white-space: nowrap;
  cursor: pointer;
  transition: background-color 120ms ease;

  svg {
    display: block;
    width: 14px;
    height: 14px;
  }

  &:hover:not(:disabled) {
    background: rgba(255, 255, 255, 0.12);
  }

  &:focus-visible {
    outline: 2px solid rgba(255, 255, 255, 0.7);
    outline-offset: 2px;
  }

  &:disabled {
    cursor: default;
    opacity: 0.5;
  }
`;

/*
 * composer は overlay のスクロール領域の中にあり、その高さがウィンドウのリサイズを
 * 決める。メニューを in-flow に置くと測定高さを押し上げ、overflow にも切られるため、
 * body へ portal して trigger のビューポート矩形に合わせて置く（computeMenuPosition）。
 * 背後の会話が透けないよう、面は不透明にする。
 */
const ModeMenu = styled.div`
  position: fixed;
  z-index: 1000;
  display: grid;
  max-width: 260px;
  padding: var(--space-xs);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  background: rgb(26, 30, 36);
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4);
`;

/** 選択中の印は CSS だけで付ける。状態は aria-checked が伝えるので本文には出さない。 */
const ModeItemLabel = styled.span``;

const ModeMenuItem = styled.button`
  justify-self: stretch;
  display: grid;
  gap: 2px;
  padding: var(--space-xs) var(--space-sm);
  border: 0;
  border-radius: 8px;
  color: var(--text-primary);
  background: transparent;
  font: inherit;
  text-align: left;
  cursor: pointer;

  &:hover {
    background: var(--surface-bg-hover);
  }

  &:focus-visible {
    outline: 2px solid currentcolor;
    outline-offset: 2px;
  }

  &[aria-checked='true'] ${ModeItemLabel}::before {
    content: '✓ ';
  }
`;

const ModeItemDescription = styled.span`
  color: var(--text-secondary);
  font-size: var(--text-meta-size);
`;

const ModeError = styled.span`
  color: rgba(254, 202, 202, 0.95);
  font-size: var(--text-meta-size);
`;

type MenuPosition = { top: number; left: number };

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), Math.max(min, max));
}

/**
 * Places the popover against the trigger inside the overlay window.
 *
 * The composer sits at the bottom of the window, so the popover normally opens
 * upward; it flips down only when the space below actually fits it.
 */
function computeMenuPosition(trigger: HTMLElement, menu: HTMLElement): MenuPosition {
  const anchor = trigger.getBoundingClientRect();
  const { offsetHeight: menuHeight, offsetWidth: menuWidth } = menu;
  const spaceBelow = window.innerHeight - anchor.bottom - ANCHOR_GAP_PX - VIEWPORT_MARGIN_PX;
  const top =
    menuHeight <= spaceBelow
      ? anchor.bottom + ANCHOR_GAP_PX
      : anchor.top - ANCHOR_GAP_PX - menuHeight;
  return {
    top: clamp(top, VIEWPORT_MARGIN_PX, window.innerHeight - menuHeight - VIEWPORT_MARGIN_PX),
    left: clamp(
      anchor.left,
      VIEWPORT_MARGIN_PX,
      window.innerWidth - menuWidth - VIEWPORT_MARGIN_PX
    ),
  };
}

type ApprovalModeMenuProps = {
  approvalMode: ActionApprovalModeControl;
};

/** Changes only this conversation, including its draft before the first submission. */
export function ApprovalModeMenu({ approvalMode }: ApprovalModeMenuProps) {
  const { t } = useI18n();
  const { mode, errorKey, isSaving, selectMode, reset } = approvalMode;
  const [isOpen, setIsOpen] = useState(false);
  const [position, setPosition] = useState<MenuPosition>({ top: 0, left: 0 });
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const menuId = useId();
  const restoreRetryFocusRef = useRef(false);

  useEffect(() => {
    if (!restoreRetryFocusRef.current || (mode === null && errorKey === null)) return;
    restoreRetryFocusRef.current = false;
    if (document.activeElement === document.body) triggerRef.current?.focus();
  }, [mode, errorKey]);

  if (mode === null && isOpen) setIsOpen(false);

  const close = (returnFocus: boolean) => {
    setIsOpen(false);
    if (returnFocus) triggerRef.current?.focus();
  };

  // The overlay window resizes to the measured content height, so the popover is
  // rendered outside the measured subtree and anchored to the trigger's viewport
  // rect instead. Positioning before paint keeps it from flashing at the origin.
  useLayoutEffect(() => {
    if (!isOpen) return;
    const reposition = () => {
      const trigger = triggerRef.current;
      const menu = menuRef.current;
      if (!trigger || !menu) return;
      setPosition(computeMenuPosition(trigger, menu));
    };
    reposition();
    window.addEventListener('resize', reposition);
    window.addEventListener('scroll', reposition, true);
    return () => {
      window.removeEventListener('resize', reposition);
      window.removeEventListener('scroll', reposition, true);
    };
  }, [isOpen]);

  useEffect(() => {
    if (!isOpen) return;
    menuRef.current?.querySelector<HTMLButtonElement>('[aria-checked="true"]')?.focus();
  }, [isOpen]);

  useEffect(() => {
    if (!isOpen) return;
    const onPointerDown = (event: MouseEvent) => {
      const target = event.target as Node;
      if (menuRef.current?.contains(target) || triggerRef.current?.contains(target)) return;
      setIsOpen(false);
    };
    document.addEventListener('mousedown', onPointerDown);
    return () => document.removeEventListener('mousedown', onPointerDown);
  }, [isOpen]);

  const moveFocus = (offset: number) => {
    const items = Array.from(
      menuRef.current?.querySelectorAll<HTMLButtonElement>('[role="menuitemradio"]') ?? []
    );
    if (items.length === 0) return;
    const current = items.findIndex((item) => item === document.activeElement);
    const next = (current + offset + items.length) % items.length;
    items[next].focus();
  };

  const handleMenuKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (event.key === 'Escape') {
      event.stopPropagation();
      close(true);
      return;
    }
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      moveFocus(event.key === 'ArrowDown' ? 1 : -1);
    }
  };

  const isDisabled = (mode === null && errorKey === null) || isSaving;
  const triggerLabel = mode === null ? t('overlay.approvalMode.label') : t(MODE_LABEL_KEY[mode]);
  const TriggerIcon = mode === null ? Shield : MODE_ICON[mode];

  return (
    <ModeRoot>
      <ModeTrigger
        ref={triggerRef}
        type="button"
        aria-haspopup={errorKey ? undefined : 'menu'}
        aria-expanded={isOpen}
        aria-controls={isOpen ? menuId : undefined}
        aria-label={
          errorKey
            ? t('overlay.approvalMode.retry')
            : `${t('overlay.approvalMode.menuLabel')}: ${triggerLabel}`
        }
        disabled={isDisabled}
        title={t(errorKey ? 'overlay.approvalMode.retry' : 'overlay.approvalMode.change')}
        aria-busy={isSaving}
        onClick={() => {
          if (errorKey) {
            restoreRetryFocusRef.current = true;
            reset();
          } else {
            setIsOpen((open) => !open);
          }
        }}
      >
        <TriggerIcon strokeWidth={1.75} aria-hidden />
        <span>{errorKey ? t('overlay.approvalMode.retry') : triggerLabel}</span>
      </ModeTrigger>
      {isOpen && !isDisabled
        ? createPortal(
            <ModeMenu
              ref={menuRef}
              id={menuId}
              role="menu"
              aria-label={t('overlay.approvalMode.menuLabel')}
              style={{ top: position.top, left: position.left }}
              onKeyDown={handleMenuKeyDown}
            >
              {MODES.map((candidate) => (
                <ModeMenuItem
                  key={candidate}
                  type="button"
                  role="menuitemradio"
                  aria-checked={mode === candidate}
                  onClick={() => {
                    close(true);
                    void selectMode(candidate);
                  }}
                >
                  <ModeItemLabel>{t(MODE_LABEL_KEY[candidate])}</ModeItemLabel>
                  <ModeItemDescription>{t(MODE_DESCRIPTION_KEY[candidate])}</ModeItemDescription>
                </ModeMenuItem>
              ))}
            </ModeMenu>,
            document.body
          )
        : null}
      {errorKey ? <ModeError role="alert">{t(errorKey)}</ModeError> : null}
    </ModeRoot>
  );
}
