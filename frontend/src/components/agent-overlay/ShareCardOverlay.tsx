import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import AgentOverlayShell from './AgentOverlayShell';

const MIN_SHARECARD_HEIGHT_PX = 120;
const MAX_SHARECARD_HEIGHT_PX = 200_000;

type ShareCardPayload = {
  content: string | null;
  suggestionText: string;
  isSuggestionStreamFinished: boolean;
  isSuggestionAccepted: boolean;
  actionText: string;
  isActionStreamFinished: boolean;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object';
}

function safeParseJson(raw: string): unknown {
  try {
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

function safeParseShareCardPayload(raw: string): ShareCardPayload | null {
  try {
    const parsed = safeParseJson(raw);
    if (!isRecord(parsed)) return null;
    const p = parsed;

    const str = (v: unknown): string | null => (typeof v === 'string' ? v : null);
    const bool = (v: unknown): boolean | null => (typeof v === 'boolean' ? v : null);
    // Fail-closed: 期待した payload 以外は描画しない（main 側で timeout -> エラーになる）
    const content = p.content === null ? null : str(p.content);
    if (content === null && p.content !== null) return null;

    const suggestionText = str(p.suggestionText);
    const actionText = str(p.actionText);
    const isSuggestionStreamFinished = bool(p.isSuggestionStreamFinished);
    const isSuggestionAccepted = bool(p.isSuggestionAccepted);
    const isActionStreamFinished = bool(p.isActionStreamFinished);

    if (suggestionText === null) return null;
    if (actionText === null) return null;
    if (isSuggestionStreamFinished === null) return null;
    if (isSuggestionAccepted === null) return null;
    if (isActionStreamFinished === null) return null;

    return {
      content,
      suggestionText,
      isSuggestionStreamFinished,
      isSuggestionAccepted,
      actionText,
      isActionStreamFinished,
    };
  } catch {
    return null;
  }
}

function nextFrame(): Promise<void> {
  return new Promise((resolve) => requestAnimationFrame(() => resolve()));
}

function parsePixelValue(value: string): number {
  const parsed = Number.parseFloat(value || '0');
  return Number.isFinite(parsed) ? parsed : 0;
}

function getOuterHeightWithMargins(element: HTMLElement): number {
  const rect = element.getBoundingClientRect();
  const computed = window.getComputedStyle(element);
  return rect.height + parsePixelValue(computed.marginTop) + parsePixelValue(computed.marginBottom);
}

function getContentBottomWithinStage(stage: HTMLElement, element: HTMLElement): number {
  const stageRect = stage.getBoundingClientRect();
  const rect = element.getBoundingClientRect();
  const computed = window.getComputedStyle(element);
  const contentHeight = Math.max(rect.height, element.scrollHeight);
  return (
    rect.top -
    stageRect.top +
    contentHeight +
    parsePixelValue(computed.marginTop) +
    parsePixelValue(computed.marginBottom)
  );
}

function expandShareCardLayout(stage: HTMLElement): void {
  const elements = stage.querySelectorAll<HTMLElement>(
    "[data-sharecard-root='true'], [data-sharecard-force-visible='true'], [data-sharecard-scroll='true']"
  );
  for (const element of elements) {
    element.style.height = 'auto';
    element.style.maxHeight = 'none';
    element.style.overflow = 'visible';
  }
}

function getShareCardDocumentHeight(stage: HTMLElement, card: HTMLElement | null): number {
  const cardHeight = card ? getOuterHeightWithMargins(card) : 0;
  const documentElement = document.documentElement;
  const body = document.body;
  const measuredElements = [stage, ...Array.from(stage.querySelectorAll<HTMLElement>('*'))];
  const contentHeight = Math.max(
    stage.getBoundingClientRect().height,
    stage.scrollHeight,
    cardHeight,
    documentElement?.scrollHeight ?? 0,
    body?.scrollHeight ?? 0,
    ...measuredElements.map((element) => getContentBottomWithinStage(stage, element))
  );

  return Math.ceil(contentHeight);
}

export default function ShareCardOverlay() {
  const [payload, setPayload] = useState<ShareCardPayload | null>(null);
  const stageRef = useRef<HTMLDivElement | null>(null);
  const cardRef = useRef<HTMLDivElement | null>(null);
  const sentRef = useRef(false);

  useLayoutEffect(() => {
    document.body.classList.add('sharecard-mode');
    document.documentElement.classList.add('sharecard-mode');
    return () => {
      document.body.classList.remove('sharecard-mode');
      document.documentElement.classList.remove('sharecard-mode');
    };
  }, []);

  // set-content を受け取り、sharecard用payloadとして解釈する
  useEffect(() => {
    const onSetContent = window.electron?.agentOverlay?.onSetContent;
    if (!onSetContent) return;
    const unsubscribe = onSetContent((content) => {
      const next = safeParseShareCardPayload(content);
      if (next) {
        sentRef.current = false;
        setPayload(next);
      }
    });
    return () => {
      try {
        unsubscribe?.();
      } catch {
        // no-op
      }
    };
  }, []);

  const shellProps = useMemo(() => {
    const p = payload;
    return {
      isVisible: true,
      isContentVisible: true,
      isExpanded: true,
      content: p?.content ?? null,
      suggestionText: p?.suggestionText ?? '',
      isSuggestionStreamFinished: Boolean(p?.isSuggestionStreamFinished),
      isSuggestionAccepted: Boolean(p?.isSuggestionAccepted),
      actionText: p?.actionText ?? '',
      isActionStreamFinished: Boolean(p?.isActionStreamFinished),
      approvalUiState: 'hidden' as const,
      approvalBlockers: [],
      copyStatusAnswer: false,
      showBusyIndicator: false,
      // 操作UIはCSSで非表示にする（data-sharecard-hide）
      showFooterActions: false,
      // ShareCardモードでもアイコンを表示するためにダミー関数を渡す
      onToggleExpand: () => {},
      onClose: () => {},
      onReject: undefined,
      onCopyAnswer: undefined,
      // ShareCardモードでもアイコンを表示するためにダミー関数を渡す（実際には呼ばれない）
      onShareScreenshot: () => {},
    } as const;
  }, [payload]);

  // レイアウトが確定したら main に高さを通知する（main が setContentSize→capturePage する）
  useLayoutEffect(() => {
    if (!payload) return;
    if (sentRef.current) return;

    let cancelled = false;
    (async () => {
      try {
        // フォント/レイアウト安定待ち
        try {
          await document.fonts?.ready;
        } catch {
          // no-op
        }
        await nextFrame();
        await nextFrame();
        if (cancelled) return;

        const card = cardRef.current;
        const stage = stageRef.current;
        if (!stage) return;

        expandShareCardLayout(stage);
        await nextFrame();
        await nextFrame();
        if (cancelled) return;

        const stageHeight = getShareCardDocumentHeight(stage, card);
        const safeHeight = Math.max(
          MIN_SHARECARD_HEIGHT_PX,
          Math.min(MAX_SHARECARD_HEIGHT_PX, stageHeight)
        );

        window.electron?.ipcRenderer?.send('sharecard:ready', { height: safeHeight });
        sentRef.current = true;
      } catch {
        // no-op（main 側で timeout する）
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [payload]);

  return (
    <div ref={stageRef} className="sharecard-stage" aria-hidden>
      <div ref={cardRef} className="sharecard-card">
        <AgentOverlayShell {...shellProps} />
      </div>
    </div>
  );
}
