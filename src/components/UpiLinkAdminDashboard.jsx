import React, { useCallback, useEffect, useState } from 'react';
import {
  Copy,
  ExternalLink,
  LogOut,
  QrCode,
  RefreshCw,
  Search,
  Shield,
} from 'lucide-react';
import { formatDateTime } from '../utils/formatDateTime';

const statusLabel = (status) => {
  const s = String(status || '').toLowerCase();
  if (s === 'completed') return 'Success';
  if (s === 'failed') return 'Failed';
  if (s === 'processing') return 'Processing';
  return status || '—';
};

const promoStateLabel = (state) => {
  const s = String(state || '').toLowerCase();
  if (s === 'eligible') return 'Eligible';
  if (s === 'not_eligible' || s === 'ineligible') return 'Not eligible';
  if (s === 'already_redeemed') return 'Already redeemed';
  if (s === 'unknown') return 'Unknown';
  return state || '—';
};

const UPI_ADMIN_TABS = [
  { id: 'settings', label: 'Settings' },
  { id: 'records', label: 'Extraction records' },
];

const UpiLinkAdminDashboard = ({
  apiBase = '',
  fetchAdminAuthed,
  fetchOpts,
  adminSearch = '',
  setAdminSearch,
  onSearch,
  adminSearchLoading = false,
  handleLogout,
  hideTabNav = false,
  requestedSubTab = 'settings',
  requestedSubTabSignal = 0,
}) => {
  const [submitMode, setSubmitMode] = useState('online');
  const [submitModeSaving, setSubmitModeSaving] = useState(false);
  const [proxyMasked, setProxyMasked] = useState('');
  const [promotionProxyMasked, setPromotionProxyMasked] = useState('');
  const [proxyLoading, setProxyLoading] = useState(false);
  const [records, setRecords] = useState([]);
  const [recordsLoading, setRecordsLoading] = useState(false);
  const [recordsTotal, setRecordsTotal] = useState(0);
  const [copiedId, setCopiedId] = useState('');
  const [expandedRowId, setExpandedRowId] = useState('');
  const [adminTab, setAdminTab] = useState('settings');

  useEffect(() => {
    const next = String(requestedSubTab || '').trim();
    const hit = UPI_ADMIN_TABS.find((tab) => tab.id === next);
    setAdminTab(hit ? hit.id : 'settings');
  }, [requestedSubTab, requestedSubTabSignal]);

  const loadSubmitMode = useCallback(async () => {
    if (!apiBase || !fetchAdminAuthed) return;
    try {
      const res = await fetchAdminAuthed(
        `${apiBase}/api/settings/upi-link-submit-override?t=${Date.now()}`,
        fetchOpts('GET', null, true),
      );
      if (!res.ok) return;
      const data = await res.json();
      setSubmitMode(data.mode === 'offline' ? 'offline' : 'online');
    } catch {
      
    }
  }, [apiBase, fetchAdminAuthed, fetchOpts]);

  const loadProxy = useCallback(async () => {
    if (!apiBase || !fetchAdminAuthed) return;
    setProxyLoading(true);
    try {
      const res = await fetchAdminAuthed(
        `${apiBase}/api/settings/upi-link-proxy?t=${Date.now()}`,
        fetchOpts('GET', null, true),
      );
      if (!res.ok) return;
      const data = await res.json();
      setProxyMasked(String(data?.proxyMasked || '').trim());
      setPromotionProxyMasked(String(data?.promotionProxyMasked || '').trim());
    } catch {
      setProxyMasked('');
      setPromotionProxyMasked('');
    } finally {
      setProxyLoading(false);
    }
  }, [apiBase, fetchAdminAuthed, fetchOpts]);

  const loadRecords = useCallback(async (term) => {
    if (!apiBase || !fetchAdminAuthed) return;
    setRecordsLoading(true);
    try {
      const q = String(term || '').trim();
      const url = `${apiBase}/api/admin/upi-link-extractions?limit=80${q ? `&search=${encodeURIComponent(q)}` : ''}`;
      const res = await fetchAdminAuthed(url, fetchOpts('GET', null, true));
      if (!res.ok) {
        setRecords([]);
        setRecordsTotal(0);
        return;
      }
      const data = await res.json();
      setRecords(Array.isArray(data?.items) ? data.items : []);
      setRecordsTotal(Number(data?.total) || 0);
    } catch {
      setRecords([]);
      setRecordsTotal(0);
    } finally {
      setRecordsLoading(false);
    }
  }, [apiBase, fetchAdminAuthed, fetchOpts]);

  useEffect(() => {
    loadSubmitMode();
    loadProxy();
    loadRecords('');
  }, [loadSubmitMode, loadProxy, loadRecords]);

  useEffect(() => {
    loadRecords(adminSearch);
  }, [adminSearch, loadRecords]);

  const handleToggleSubmitMode = async () => {
    if (!apiBase || submitModeSaving || !fetchAdminAuthed) return;
    const next = submitMode === 'offline' ? 'online' : 'offline';
    setSubmitModeSaving(true);
    try {
      const res = await fetchAdminAuthed(
        `${apiBase}/api/settings/upi-link-submit-override`,
        fetchOpts('POST', { mode: next }),
      );
      const data = await res.json();
      if (!res.ok || data?.success !== true) {
        window.alert(data?.error || 'Save failed');
        return;
      }
      setSubmitMode(next);
    } catch {
      window.alert('Save failed. Please try again later.');
    } finally {
      setSubmitModeSaving(false);
    }
  };

  const copyText = async (value, id) => {
    const text = String(value || '').trim();
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
      setCopiedId(String(id || text));
      window.setTimeout(() => setCopiedId(''), 1800);
    } catch {
      window.alert('Copy failed');
    }
  };

  const renderStatusBadge = (status) => {
    const s = String(status || '').toLowerCase();
    const ok = s === 'completed';
    const pending = s === 'processing';
    return (
      <span className={ok ? 'text-emerald-600' : pending ? 'text-amber-600' : 'text-rose-600'}>
        {statusLabel(status)}
      </span>
    );
  };

  const renderLinkCell = (row) => (
    row.longUrl ? (
      <div className="flex items-start gap-2">
        <code className="min-w-0 flex-1 break-all rounded-lg border border-slate-200 bg-white px-2 py-1.5 font-mono text-xs text-emerald-700">
          {row.longUrl}
        </code>
        <div className="flex shrink-0 flex-col gap-1">
          <button
            type="button"
            onClick={() => copyText(row.longUrl, row.id)}
            className="rounded-lg border border-slate-200 bg-white p-2 text-slate-600 hover:bg-slate-50"
            title="Copy link"
          >
            <Copy size={14} />
          </button>
          <a
            href={row.longUrl}
            target="_blank"
            rel="noreferrer"
            className="rounded-lg border border-slate-200 bg-white p-2 text-slate-600 hover:bg-slate-50"
            title="Open link"
          >
            <ExternalLink size={14} />
          </a>
        </div>
      </div>
    ) : (
      <span className="text-slate-400">{row.longUrlMasked || '—'}</span>
    )
  );

  const renderDebugPanel = (row) => {
    const steps = Array.isArray(row.steps) ? row.steps : [];
    const debug = row.debug && typeof row.debug === 'object' ? row.debug : {};
    return (
      <div className="space-y-3 rounded-xl border border-slate-200 bg-slate-50 p-3 text-xs">
        <div className="grid gap-2 md:grid-cols-2">
          <div>
            <p className="font-semibold text-slate-600">Fail stage</p>
            <p className="font-mono text-slate-800">{row.failStage || '—'}</p>
          </div>
          <div>
            <p className="font-semibold text-slate-600">Amount (paise)</p>
            <p className="font-mono text-slate-800">{row.amount ?? '—'}</p>
          </div>
        </div>
        {row.messageRaw ? (
          <div>
            <p className="mb-1 font-semibold text-slate-600">Raw error</p>
            <code className="block whitespace-pre-wrap break-all rounded-lg border border-slate-200 bg-white p-2 font-mono text-[11px] text-rose-700">
              {row.messageRaw}
            </code>
          </div>
        ) : null}
        {Object.keys(debug).length > 0 ? (
          <div>
            <p className="mb-1 font-semibold text-slate-600">Proxy / debug</p>
            <code className="block whitespace-pre-wrap break-all rounded-lg border border-slate-200 bg-white p-2 font-mono text-[11px] text-slate-700">
              {JSON.stringify(debug, null, 2)}
            </code>
          </div>
        ) : null}
        {steps.length > 0 ? (
          <div>
            <p className="mb-1 font-semibold text-slate-600">Step trail ({steps.length})</p>
            <div className="max-h-56 space-y-1 overflow-auto rounded-lg border border-slate-200 bg-white p-2">
              {steps.map((step, idx) => (
                <div key={`${row.id}-step-${idx}`} className="font-mono text-[11px] leading-5 text-slate-700">
                  <span className={step.status === 'ok' ? 'text-emerald-600' : step.status === 'warn' ? 'text-amber-600' : 'text-slate-500'}>
                    [{step.status || 'info'}]
                  </span>
                  {' '}
                  {step.name}
                  {step.detail ? `: ${step.detail}` : ''}
                </div>
              ))}
            </div>
          </div>
        ) : null}
        <p className="text-[11px] text-slate-500">Full JSON: run-output/upi-link-debug/{row.jobId || row.id}.json</p>
      </div>
    );
  };

  return (
    <div className="space-y-6">
      <div className="admin-page-header p-5 md:p-6">
        <div className="mb-5 flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
          <div>
            <h2 className="tech-title text-2xl font-semibold text-slate-900">ChatGPT UPI Link Admin</h2>
            {!hideTabNav ? (
              <div className="mt-4 flex flex-wrap gap-2">
                {UPI_ADMIN_TABS.map((tab) => (
                  <button
                    key={tab.id}
                    type="button"
                    onClick={() => setAdminTab(tab.id)}
                    className={`rounded-full px-4 py-1.5 text-sm font-bold transition-colors ${
                      adminTab === tab.id
                        ? 'bg-slate-900 text-white'
                        : 'bg-white text-slate-600 border border-slate-200 hover:bg-slate-50'
                    }`}
                  >
                    {tab.label}
                  </button>
                ))}
              </div>
            ) : null}
          </div>
          <button
            type="button"
            onClick={handleLogout}
            className="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-4 py-2.5 text-sm font-medium text-slate-600 hover:text-slate-900"
          >
            <LogOut size={16} />
            Sign out
          </button>
        </div>

        {adminTab === 'settings' ? (
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <div className="rounded-2xl surface-panel p-5">
              <div className="mb-3 flex items-center gap-2">
                <Shield size={16} className="text-slate-500" />
                <p className="text-sm font-bold text-slate-900">Public switch</p>
              </div>
              <p className="mb-4 text-sm text-slate-600">
                When offline, the public &quot;ChatGPT UPI free link&quot; tool shows maintenance mode and rejects submissions.
              </p>
              <div className="flex flex-wrap items-center gap-3">
                <span className={`rounded-full px-3 py-1 text-xs font-bold ${submitMode === 'online' ? 'bg-emerald-50 text-emerald-700 border border-emerald-200' : 'bg-rose-50 text-rose-700 border border-rose-200'}`}>
                  {submitMode === 'online' ? 'Online' : 'Maintenance'}
                </span>
                <button
                  type="button"
                  disabled={submitModeSaving}
                  onClick={handleToggleSubmitMode}
                  className="rounded-xl bg-slate-900 px-4 py-2 text-sm font-bold text-white hover:bg-slate-800 disabled:opacity-60"
                >
                  {submitModeSaving ? 'Saving…' : (submitMode === 'online' ? 'Switch to maintenance' : 'Switch to online')}
                </button>
              </div>
            </div>

            <div className="rounded-2xl surface-panel p-5">
              <div className="mb-3 flex items-center gap-2">
                <QrCode size={16} className="text-slate-500" />
                <p className="text-sm font-bold text-slate-900">User submission notes</p>
              </div>
              <ul className="space-y-2 text-sm leading-6 text-slate-600">
                <li>1. User must be signed in (free tool; no license key)</li>
                <li>2. Paste full Session JSON (accessToken + sessionToken)</li>
                <li>3. Account must be Free and eligible for ChatGPT first-month free promo</li>
                <li>4. Prefer running a trial eligibility check before extraction</li>
                <li>5. Extraction usually takes 30–90 seconds; do not close the page</li>
              </ul>
            </div>

            <div className="rounded-2xl surface-panel p-5 lg:col-span-2">
              <div className="mb-3 flex items-center gap-2">
                <Shield size={16} className="text-slate-500" />
                <p className="text-sm font-bold text-slate-900">Proxy configuration (read-only)</p>
                {proxyLoading ? <span className="text-xs text-slate-400">Loading…</span> : null}
              </div>
              <p className="mb-3 text-sm text-slate-600">
                Flow: <strong>India</strong> checkout → <strong>Vietnam</strong> promo (dedicated IP + vi-VN) → cool-down then <strong>re-enter India</strong> (new oai-did / new egress) → UPI / approve. Configure via <code className="rounded bg-slate-100 px-1.5 py-0.5 text-xs">env_upi_link.txt</code> or environment variables.
              </p>
              <div className="space-y-2">
                <div>
                  <p className="mb-1 text-xs font-semibold text-slate-500">India UPI proxy (UPI_LINK_PROXY)</p>
                  <code className="block break-all rounded-xl border border-slate-200 bg-white px-3 py-2.5 font-mono text-xs text-slate-700">
                    {proxyMasked || '(not configured)'}
                  </code>
                </div>
                <div>
                  <p className="mb-1 text-xs font-semibold text-slate-500">Vietnam promo proxy (UPI_LINK_PROMOTION_PROXY)</p>
                  <code className="block break-all rounded-xl border border-slate-200 bg-white px-3 py-2.5 font-mono text-xs text-slate-700">
                    {promotionProxyMasked || '(not configured)'}
                  </code>
                </div>
              </div>
            </div>
          </div>
        ) : null}
      </div>

      {adminTab === 'records' ? (
        <div className="rounded-[2rem] surface-panel p-5 md:p-6">
          <div className="mb-4 flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
            <div>
              <p className="text-lg font-black text-slate-900">UPI extraction records</p>
              <p className="text-sm text-slate-500">{recordsTotal} total (showing latest 80, including full payment links)</p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <form
                className="flex w-full min-w-0 flex-1 items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 py-2 md:min-w-[240px]"
                onSubmit={(e) => {
                  e.preventDefault();
                  onSearch?.(adminSearch);
                }}
              >
                <Search size={16} className="shrink-0 text-slate-400" />
                <input
                  type="text"
                  value={adminSearch}
                  onChange={(e) => setAdminSearch?.(e.target.value)}
                  placeholder="Search email / user ID / record ID / error"
                  className="min-w-0 flex-1 bg-transparent text-sm outline-none"
                />
              </form>
              <button
                type="button"
                onClick={() => loadRecords(adminSearch)}
                disabled={recordsLoading}
                className="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-60"
              >
                <RefreshCw size={15} className={recordsLoading ? 'animate-spin' : ''} />
                Refresh
              </button>
            </div>
          </div>

          {adminSearchLoading || recordsLoading ? (
            <p className="py-8 text-center text-sm text-slate-500">Loading…</p>
          ) : records.length === 0 ? (
            <p className="py-8 text-center text-sm text-slate-500">No extraction records</p>
          ) : (
            <>
              <div className="space-y-3 md:hidden">
                {records.map((row) => (
                  <div
                    key={row.id}
                    className="rounded-2xl border border-slate-200 bg-white/90 p-4 shadow-sm"
                  >
                    <div className="mb-3 flex items-start justify-between gap-3">
                      <p className="text-xs leading-5 text-slate-500">
                        {formatDateTime(row.timestamp)}
                      </p>
                      {renderStatusBadge(row.status)}
                    </div>
                    <dl className="space-y-3 text-sm">
                      <div>
                        <dt className="mb-1 text-xs font-medium text-slate-500">User ID</dt>
                        <dd className="break-all font-mono text-xs leading-5 text-slate-700">{row.userId || '—'}</dd>
                      </div>
                      <div>
                        <dt className="mb-1 text-xs font-medium text-slate-500">Email</dt>
                        <dd className="break-all leading-5 text-slate-800">{row.email || '—'}</dd>
                      </div>
                      <div className="flex flex-wrap gap-4">
                        <div>
                          <dt className="mb-1 text-xs font-medium text-slate-500">Promo eligibility</dt>
                          <dd className="text-slate-800">{promoStateLabel(row.promoState)}</dd>
                        </div>
                        <div>
                          <dt className="mb-1 text-xs font-medium text-slate-500">Currency</dt>
                          <dd className="text-slate-800">{row.currency || 'INR'}</dd>
                        </div>
                      </div>
                      <div>
                        <dt className="mb-1 text-xs font-medium text-slate-500">UPI link</dt>
                        <dd>{renderLinkCell(row)}</dd>
                        {copiedId === row.id ? (
                          <p className="mt-1 text-xs text-emerald-600">Copied</p>
                        ) : null}
                      </div>
                      {row.message ? (
                        <div>
                          <dt className="mb-1 text-xs font-medium text-slate-500">Notes</dt>
                          <dd className="break-words text-xs leading-5 text-slate-500">{row.message}</dd>
                        </div>
                      ) : null}
                      {(row.messageRaw || (row.steps && row.steps.length) || row.failStage) ? (
                        <div>
                          <button
                            type="button"
                            onClick={() => setExpandedRowId((prev) => (prev === row.id ? '' : row.id))}
                            className="text-xs font-semibold text-slate-700 underline"
                          >
                            {expandedRowId === row.id ? 'Hide diagnostics' : 'View diagnostics'}
                          </button>
                          {expandedRowId === row.id ? renderDebugPanel(row) : null}
                        </div>
                      ) : null}
                    </dl>
                  </div>
                ))}
              </div>

              <div className="hidden overflow-x-auto md:block">
                <table className="w-max min-w-full text-left text-sm">
                  <thead>
                    <tr className="border-b border-slate-200 text-xs uppercase tracking-wide text-slate-500">
                      <th className="whitespace-nowrap px-3 py-3 font-medium">Time</th>
                      <th className="whitespace-nowrap px-3 py-3 font-medium">User ID</th>
                      <th className="whitespace-nowrap px-3 py-3 font-medium">Email</th>
                      <th className="whitespace-nowrap px-3 py-3 font-medium">Promo</th>
                      <th className="min-w-[320px] whitespace-nowrap px-3 py-3 font-medium">UPI link</th>
                      <th className="whitespace-nowrap px-3 py-3 font-medium">Status</th>
                      <th className="min-w-[200px] whitespace-nowrap px-3 py-3 font-medium">Notes</th>
                      <th className="whitespace-nowrap px-3 py-3 font-medium">Diagnostics</th>
                    </tr>
                  </thead>
                  <tbody>
                    {records.map((row) => (
                      <React.Fragment key={row.id}>
                      <tr className="border-b border-slate-100 align-top hover:bg-slate-50/70">
                        <td className="whitespace-nowrap px-3 py-3 text-slate-600">
                          {formatDateTime(row.timestamp)}
                        </td>
                        <td className="max-w-[220px] px-3 py-3 font-mono text-xs text-slate-600">
                          <span className="block truncate" title={row.userId || ''}>{row.userId || '—'}</span>
                        </td>
                        <td className="max-w-[240px] px-3 py-3 text-slate-700">
                          <span className="block truncate" title={row.email || ''}>{row.email || '—'}</span>
                        </td>
                        <td className="whitespace-nowrap px-3 py-3 text-slate-700">
                          {promoStateLabel(row.promoState)}
                        </td>
                        <td className="min-w-[320px] px-3 py-3">
                          {renderLinkCell(row)}
                          {copiedId === row.id ? (
                            <p className="mt-1 text-xs text-emerald-600">Copied</p>
                          ) : null}
                        </td>
                        <td className="whitespace-nowrap px-3 py-3">
                          {renderStatusBadge(row.status)}
                        </td>
                        <td className="max-w-[280px] px-3 py-3 text-xs text-slate-500">
                          <span className="block break-words" title={row.message || ''}>{row.message || '—'}</span>
                          {row.failStage ? (
                            <span className="mt-1 block font-mono text-[11px] text-rose-600">{row.failStage}</span>
                          ) : null}
                        </td>
                        <td className="px-3 py-3 text-xs">
                          {(row.messageRaw || (row.steps && row.steps.length) || row.failStage) ? (
                            <button
                              type="button"
                              onClick={() => setExpandedRowId((prev) => (prev === row.id ? '' : row.id))}
                              className="font-semibold text-slate-700 underline"
                            >
                              {expandedRowId === row.id ? 'Collapse' : 'Expand'}
                            </button>
                          ) : '—'}
                        </td>
                      </tr>
                      {expandedRowId === row.id ? (
                        <tr key={`${row.id}-debug`} className="border-b border-slate-100 bg-slate-50/80">
                          <td colSpan={8} className="px-3 py-3">
                            {renderDebugPanel(row)}
                          </td>
                        </tr>
                      ) : null}
                      </React.Fragment>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </div>
      ) : null}
    </div>
  );
};

export default UpiLinkAdminDashboard;
