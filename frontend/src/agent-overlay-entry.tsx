import React from 'react';
import ReactDOM from 'react-dom/client';
import AgentOverlay from './components/AgentOverlay';
import ShareCardOverlay from './components/agent-overlay/ShareCardOverlay';
import { UiLanguageProvider } from './context/UiLanguageContext';
import { resolveRendererInitialLanguage } from './i18n/initialLanguage';
import './index.css';

type OverlayEntry = { mode: 'overlay' | 'standalone' | 'sharecard'; actionId: string | null };

function getEntry(): OverlayEntry {
  try {
    const url = new URL(window.location.href);
    const mode = url.searchParams.get('mode');
    const actionId = url.searchParams.get('actionId');
    return {
      mode: mode === 'sharecard' || mode === 'standalone' ? mode : 'overlay',
      actionId: actionId?.trim() || null,
    };
  } catch {
    return { mode: 'overlay', actionId: null };
  }
}

const initialLanguage = resolveRendererInitialLanguage();
const entry = getEntry();

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <UiLanguageProvider initialLanguage={initialLanguage}>
      {entry.mode === 'sharecard' ? (
        <ShareCardOverlay />
      ) : (
        <AgentOverlay
          entryMode={entry.mode === 'standalone' ? 'standalone' : 'overlay'}
          initialActionId={entry.actionId}
        />
      )}
    </UiLanguageProvider>
  </React.StrictMode>
);
