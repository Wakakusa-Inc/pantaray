import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { MarkdownBlock } from './MarkdownRenderer';

describe('MarkdownBlock', () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    delete window.electron;
  });

  it('reveals pantaray-file links by decoded absolute path without an action', async () => {
    const open = vi.fn(async () => undefined);
    window.electron = { actionFiles: { open } } as unknown as Window['electron'];

    render(
      <MarkdownBlock
        isStreamFinished
        text="[資料フォルダ](pantaray-file:///Users/name/My%20Docs/%E8%B3%87%E6%96%99)"
      />
    );

    fireEvent.click(screen.getByRole('link', { name: '資料フォルダ' }));

    await waitFor(() => {
      expect(open).toHaveBeenCalledWith({ path: '/Users/name/My Docs/資料' });
    });
  });
});
