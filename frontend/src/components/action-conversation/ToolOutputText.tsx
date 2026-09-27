import { useLayoutEffect, useRef, useState } from 'react';

/**
 * ツール出力の箱。折り返しと高さ上限は CSS が持つ（.action-conversation__tool-output-text）。
 * キーボードで焦点を持つのは、描画した結果として実際に縦へはみ出した箱だけにする。文字数や行数
 * では決められない（折り返す幅しだいで、短くてもはみ出すし、長くても収まる）。幅が変われば
 * 折り返しも変わるので、寸法が動くたびに測り直す。収まっている箱まで焦点を持つと、会話を辿る
 * タブ移動が無駄に増える。
 */
export function ToolOutputText({ content, label }: { content: string; label: string }) {
  const ref = useRef<HTMLPreElement>(null);
  const [scrollable, setScrollable] = useState(false);

  useLayoutEffect(() => {
    const element = ref.current;
    if (element === null) return;
    const measure = () => setScrollable(element.scrollHeight > element.clientHeight);
    measure();
    // ResizeObserver を持たない DOM 実装では、描画直後の 1 回の測定だけで済ませる。
    if (typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, [content]);

  return (
    <pre
      ref={ref}
      className="action-conversation__tool-output-text"
      aria-label={label}
      role={scrollable ? 'group' : undefined}
      tabIndex={scrollable ? 0 : undefined}
    >
      {content}
    </pre>
  );
}
