import React from 'react';

/**
 * Optional helper control used by the host portal.
 * In this standalone package it is a no-op placeholder so embeds still compile.
 * Host apps can replace this component with their own session-extractor UI.
 */
export default function GptSessionExtractButton({
  language = 'en',
  disabled = false,
  className = '',
  onClick,
}) {
  if (typeof onClick !== 'function') {
    return null;
  }

  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className={
        className
        || 'inline-flex items-center justify-center rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50'
      }
    >
      Extract session
    </button>
  );
}
