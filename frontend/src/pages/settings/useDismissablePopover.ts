import { useCallback, useEffect, useRef, type RefObject } from 'react';

const FIRST_FIELD_SELECTOR =
  'input:not([disabled]), select:not([disabled]), textarea:not([disabled]), button:not([disabled]), [tabindex]:not([tabindex="-1"])';

interface DismissablePopoverOptions {
  isOpen: boolean;
  triggerRef: RefObject<HTMLButtonElement>;
  onDismiss: () => void;
}

export function useDismissablePopover(options: DismissablePopoverOptions) {
  const { isOpen, onDismiss, triggerRef } = options;
  const popoverRef = useRef<HTMLDivElement>(null);

  const dismiss = useCallback(() => {
    onDismiss();
    triggerRef.current?.focus();
  }, [onDismiss, triggerRef]);

  useEffect(() => {
    if (!isOpen) return;

    const popover = popoverRef.current;
    const firstField = popover?.querySelector<HTMLElement>(FIRST_FIELD_SELECTOR);
    (firstField ?? popover)?.focus();

    const dismissOnEscape = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      event.preventDefault();
      dismiss();
    };
    const dismissOnOutsidePointerDown = (event: PointerEvent) => {
      const target = event.target as Node;
      if (popover?.contains(target) || triggerRef.current?.contains(target)) return;
      onDismiss();
    };

    document.addEventListener('keydown', dismissOnEscape);
    document.addEventListener('pointerdown', dismissOnOutsidePointerDown);
    return () => {
      document.removeEventListener('keydown', dismissOnEscape);
      document.removeEventListener('pointerdown', dismissOnOutsidePointerDown);
    };
  }, [dismiss, isOpen, onDismiss, triggerRef]);

  return { dismiss, popoverRef };
}
