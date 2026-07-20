import React from 'react';

/**
 * Lightweight toast banner for portal embeds.
 * Expects toast = { type: 'success'|'error'|'info'|'', text: string }
 */
export default function PortalToast({ toast }) {
  const text = String(toast?.text || '').trim();
  if (!text) return null;

  const type = String(toast?.type || 'info').toLowerCase();
  const tone =
    type === 'error'
      ? 'border-rose-200 bg-rose-50 text-rose-900'
      : type === 'success'
        ? 'border-emerald-200 bg-emerald-50 text-emerald-900'
        : 'border-slate-200 bg-slate-50 text-slate-800';

  return (
    <div
      role="status"
      className={`fixed bottom-5 right-5 z-50 max-w-sm rounded-xl border px-4 py-3 text-sm shadow-lg ${tone}`}
    >
      {text}
    </div>
  );
}
