import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Copy, ExternalLink, Loader2, QrCode, Wrench } from 'lucide-react';
import GptSessionExtractButton from './GptSessionExtractButton';
import PortalToast from './PortalToast';
import { portalCsrfPost } from '../utils/portalCsrfRequest';
import { gptToolUsageBundle } from '../constants/gptUsageNotes';

const HISTORY_KEY = 'portal_upi_link_history_v1';
const MAX_LOCAL_HISTORY = 15;

const readLocalHistory = () => {
    try {
        const raw = localStorage.getItem(HISTORY_KEY);
        const list = JSON.parse(raw || '[]');
        return Array.isArray(list) ? list : [];
    } catch {
        return [];
    }
};

const appendLocalHistory = (entry) => {
    if (!entry?.long_url) return;
    try {
        const list = readLocalHistory().filter((item) => item?.id !== entry.id);
        list.unshift(entry);
        localStorage.setItem(HISTORY_KEY, JSON.stringify(list.slice(0, MAX_LOCAL_HISTORY)));
    } catch {
        
    }
};

export default function UpiLinkExtractorTool({
    language = 'en',
    apiBase = '',
    fetchOpts,
    csrfToken = '',
    ensureCsrfToken,
    onCsrfToken,
}) {
    const usage = useMemo(() => gptToolUsageBundle('en', 'upiLink'), []);

    const text = {
        title: 'ChatGPT UPI Free Link',
        tokenLabel: 'Session JSON',
        tokenPlaceholder: 'Paste full session JSON (accessToken + sessionToken)',
        submit: 'Generate UPI Link',
        submitting: 'Extracting…',
        progress: 'Progress',
        progressHint: 'Generating UPI link, please wait…',
        queueTitle: 'Queue',
        queueRunning: 'Extracting your account. Please wait…',
        queueWaiting: 'Another extraction is in progress. Waiting in queue…',
        queueWaitingAhead: (n) => `${n} task(s) ahead of you. Please wait…`,
        queueNote: 'Only one account can be extracted at a time.',
        resultEmpty: 'After success, the UPI payment link will appear here',
        resultTitle: 'UPI Payment Link',
        link: 'Payment link',
        open: 'Open link',
        copy: 'Copy',
        copied: 'Copied',
        hint: 'Share with Indian users — PhonePe / GPay / Paytm.',
        history: 'My extraction records',
        historyEmpty: 'No records yet',
        historyHint: 'Free for logged-in users; recent links saved on this device',
        emptyToken: 'Please paste session JSON first',
        failGeneric: 'Extraction failed. Please try again.',
        failTimeout: 'Timed out. Please try again.',
        needLogin: 'Please sign in first.',
        offline: 'UPI link extraction is under maintenance. Please try again later.',
        copyFail: 'Copy failed',
        clear: 'Clear input',
        viewLink: 'View link',
        hideLink: 'Hide',
        statusDone: 'Completed',
        refresh: 'Refresh',
    };

    const [token, setToken] = useState('');
    const [loading, setLoading] = useState(false);
    const [progress, setProgress] = useState(0);
    const [toast, setToast] = useState({ type: '', text: '' });
    const [liveResult, setLiveResult] = useState(null);
    const [history, setHistory] = useState(() => readLocalHistory());
    const [selectedId, setSelectedId] = useState('');
    const [copiedKey, setCopiedKey] = useState('');
    const [submitMode, setSubmitMode] = useState('online');
    const [queueInfo, setQueueInfo] = useState({ status: '', ahead: 0, size: 0 });
    const pollRef = useRef(null);

    const applyQueuePayload = useCallback((data) => {
        if (!data || typeof data !== 'object') return;
        setQueueInfo({
            status: String(data.queue_status || '').toLowerCase(),
            ahead: Number(data.queue_ahead) || 0,
            size: Number(data.queue_size) || 0,
        });
    }, []);

    const queueHint = useMemo(() => {
        const status = queueInfo.status;
        const ahead = queueInfo.ahead;
        if (status === 'queued') {
            if (ahead > 1) return text.queueWaitingAhead(ahead);
            return text.queueWaiting;
        }
        if (status === 'running') return text.queueRunning;
        return text.progressHint;
    }, [queueInfo, text]);

    const buildGetOpts = useCallback(() => (
        typeof fetchOpts === 'function'
            ? fetchOpts('GET', null, true)
            : { method: 'GET', credentials: 'include', cache: 'no-store' }
    ), [fetchOpts]);

    const showToast = useCallback((type, msg) => {
        if (!msg) return;
        setToast({ type, text: String(msg) });
    }, []);

    useEffect(() => {
        if (!toast.text) return undefined;
        const timer = window.setTimeout(() => setToast({ type: '', text: '' }), 3200);
        return () => window.clearTimeout(timer);
    }, [toast]);

    useEffect(() => () => {
        if (pollRef.current) clearInterval(pollRef.current);
    }, []);

    useEffect(() => {
        if (!apiBase) return;
        fetch(`${apiBase}/api/settings/upi-link-submit-override?t=${Date.now()}`, buildGetOpts())
            .then((r) => (r.ok ? r.json() : {}))
            .then((data) => setSubmitMode(data?.mode === 'offline' ? 'offline' : 'online'))
            .catch(() => {});
    }, [apiBase, buildGetOpts]);

    const POLL_MAX = 180;
    const POLL_INTERVAL_MS = 2000;

    const pollJob = useCallback(async (jobId) => {
        for (let i = 0; i < POLL_MAX; i += 1) {
            await new Promise((r) => { window.setTimeout(r, POLL_INTERVAL_MS); });
            setProgress(Math.min(92, 12 + Math.round((i / POLL_MAX) * 78)));
            try {
                const opts = typeof fetchOpts === 'function'
                    ? fetchOpts('GET', null, true)
                    : { method: 'GET', credentials: 'include', cache: 'no-store' };
                const res = await fetch(
                    `${apiBase}/api/portal/tools/upi-link/status?job_id=${encodeURIComponent(jobId)}&t=${Date.now()}`,
                    opts,
                );
                const data = await res.json().catch(() => ({}));
                const status = String(data?.status || '').toLowerCase();
                if (status === 'processing') {
                    applyQueuePayload(data);
                    continue;
                }
                if (status === 'completed' && String(data?.long_url || '').trim()) {
                    return { ok: true, long_url: String(data.long_url).trim() };
                }
                if (status === 'failed') {
                    return { ok: false, error: data?.error || text.failGeneric };
                }
            } catch {
                
            }
        }
        return { ok: false, error: text.failTimeout };
    }, [apiBase, fetchOpts, text.failGeneric, text.failTimeout, applyQueuePayload]);

    const onSubmit = async (event) => {
        event.preventDefault();
        if (loading || submitMode === 'offline') return;
        const raw = token.trim();
        if (!raw) {
            showToast('error', text.emptyToken);
            return;
        }

        setLoading(true);
        setProgress(8);
        setLiveResult(null);
        setSelectedId('');
        setQueueInfo({ status: '', ahead: 0, size: 0 });

        const tick = window.setInterval(() => {
            setProgress((p) => (p >= 12 ? p : p + 1));
        }, 1500);

        try {
            const { res, data } = await portalCsrfPost({
                apiBase,
                path: '/api/portal/tools/upi-link/extract',
                body: { access_token: raw },
                fetchOpts,
                ensureCsrfToken,
                onCsrfToken,
            });
            if (!res.ok || data?.success !== true || !data?.job_id) {
                const errMsg = data?.error || text.failGeneric;
                if (res.status === 403 && String(errMsg).includes('CSRF')) {
                    showToast('error', 'Session expired. Please refresh and try again.');
                } else {
                    showToast('error', errMsg);
                }
                return;
            }
            applyQueuePayload(data);
            const polled = await pollJob(data.job_id);
            if (!polled.ok) {
                showToast('error', polled.error || text.failGeneric);
                return;
            }
            const entry = {
                id: `upi-${Date.now()}`,
                status: 'completed',
                long_url: polled.long_url,
                createdAt: Date.now(),
            };
            appendLocalHistory(entry);
            setHistory(readLocalHistory());
            setLiveResult(entry);
            setSelectedId(entry.id);
            setProgress(100);
            showToast('success', 'Link ready');
        } catch (error) {
            const msg = String(error?.message || '').trim();
            showToast('error', msg || text.failGeneric);
        } finally {
            window.clearInterval(tick);
            setLoading(false);
            setQueueInfo({ status: '', ahead: 0, size: 0 });
            setProgress((p) => (p >= 100 ? 100 : 0));
        }
    };

    const copyText = async (value, key) => {
        const val = String(value || '').trim();
        if (!val) return;
        try {
            await navigator.clipboard.writeText(val);
            setCopiedKey(key);
            window.setTimeout(() => setCopiedKey(''), 1800);
        } catch {
            showToast('error', text.copyFail);
        }
    };

    const toggleRecord = useCallback((id) => {
        const rowId = String(id || '').trim();
        if (!rowId) return;
        setSelectedId((prev) => (prev === rowId ? '' : rowId));
    }, []);

    const showProgress = loading || (progress > 0 && progress < 100);
    const displayResult = liveResult?.long_url ? liveResult : null;

    return (
        <div className="space-y-8">
            <PortalToast toast={toast} />

            <div className="surface-panel rounded-xl p-6 md:p-8">
                <div className="flex items-start gap-3 mb-6">
                    <Wrench size={20} className="text-slate-600 mt-0.5 shrink-0" />
                    <div>
                        <h2 className="text-lg font-semibold text-slate-900">{text.title}</h2>
                    </div>
                </div>

                <div className="rounded-xl border border-slate-200 bg-slate-50/90 px-5 py-4 mb-8">
                    <p className="mb-3 text-sm font-semibold text-slate-900">{usage.title}</p>
                    <ol className="text-sm text-slate-600 space-y-2.5 list-decimal list-inside leading-relaxed">
                        {usage.lines.map((line) => (
                            <li key={line}>{line}</li>
                        ))}
                    </ol>
                </div>

                {submitMode === 'offline' && (
                    <div className="mb-6 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
                        {text.offline}
                    </div>
                )}

                <form onSubmit={onSubmit} className="grid grid-cols-1 lg:grid-cols-2 gap-6 items-stretch">
                    <div className="flex flex-col gap-4 h-full min-h-[280px]">
                        <div className="flex flex-col flex-1 min-h-0">
                            <label className="text-[11px] font-medium text-neutral-500 uppercase tracking-wider">{text.tokenLabel}</label>
                            <textarea
                                value={token}
                                onChange={(e) => setToken(e.target.value)}
                                placeholder={text.tokenPlaceholder}
                                disabled={loading || submitMode === 'offline'}
                                className="mt-2 flex-1 min-h-[160px] w-full px-4 py-3 bg-white border border-neutral-200 rounded-xl font-mono text-xs leading-relaxed outline-none focus:border-neutral-400 disabled:bg-neutral-100 resize-y"
                                spellCheck={false}
                            />
                            <GptSessionExtractButton language="en" disabled={loading || submitMode === 'offline'} className="mt-2 shrink-0" />
                        </div>
                        <div className="flex flex-wrap gap-3 shrink-0">
                            <button
                                type="submit"
                                disabled={loading || submitMode === 'offline'}
                                className="flex-1 min-w-[160px] inline-flex items-center justify-center gap-2 px-6 py-3.5 rounded-xl bg-slate-900 text-white font-medium disabled:opacity-50"
                            >
                                {loading ? <Loader2 size={18} className="animate-spin" /> : <QrCode size={18} />}
                                {loading ? text.submitting : text.submit}
                            </button>
                            <button
                                type="button"
                                disabled={loading || submitMode === 'offline'}
                                onClick={() => setToken('')}
                                className="px-5 py-3.5 rounded-xl bg-slate-100 text-slate-800 text-sm font-medium hover:bg-slate-200 disabled:opacity-50"
                            >
                                {text.clear}
                            </button>
                        </div>
                    </div>

                    <div className="flex flex-col h-full min-h-[280px]">
                        {showProgress ? (
                            <div className="flex-1 h-full rounded-xl border border-slate-200 p-5 flex flex-col justify-center">
                                <p className="text-sm font-medium text-slate-800">{text.progress}</p>
                                {(queueInfo.status === 'queued' || queueInfo.status === 'running') ? (
                                    <div
                                        className={`mt-3 rounded-lg border px-3 py-2.5 text-xs leading-relaxed ${
                                            queueInfo.status === 'queued'
                                                ? 'border-amber-200 bg-amber-50 text-amber-900'
                                                : 'border-sky-200 bg-sky-50 text-sky-900'
                                        }`}
                                    >
                                        <p className="font-medium">{text.queueTitle}</p>
                                        <p className="mt-1">{queueHint}</p>
                                        {queueInfo.size > 1 && (
                                            <p className="mt-1 opacity-80">
                                                {`Queue: ${queueInfo.size} task(s) total`}
                                            </p>
                                        )}
                                        <p className="mt-1 opacity-70">{text.queueNote}</p>
                                    </div>
                                ) : (
                                    <p className="text-xs text-slate-500 mt-1">{text.progressHint}</p>
                                )}
                                <div className="mt-4 h-2 rounded-full bg-slate-100 overflow-hidden">
                                    <div
                                        className="h-full bg-slate-800 transition-all duration-500"
                                        style={{ width: `${Math.max(5, progress)}%` }}
                                    />
                                </div>
                            </div>
                        ) : displayResult ? (
                            <div className="flex-1 h-full rounded-xl border border-slate-200 p-5 flex flex-col space-y-4">
                                <p className="text-sm font-medium text-slate-800">{text.resultTitle}</p>
                                <p className="text-xs text-slate-500">{text.hint}</p>
                                <div className="mt-auto space-y-2">
                                    <p className="text-xs text-slate-500">{text.link}</p>
                                    <a
                                        href={displayResult.long_url}
                                        target="_blank"
                                        rel="noreferrer"
                                        className="block text-xs break-all text-emerald-700 hover:underline"
                                    >
                                        {displayResult.long_url}
                                    </a>
                                    <div className="flex flex-wrap gap-2 pt-1">
                                        <a
                                            href={displayResult.long_url}
                                            target="_blank"
                                            rel="noreferrer"
                                            className="inline-flex items-center gap-1 px-3 py-1.5 text-xs border rounded-lg bg-white"
                                        >
                                            <ExternalLink size={14} />
                                            {text.open}
                                        </a>
                                        <button
                                            type="button"
                                            onClick={() => copyText(displayResult.long_url, 'live-link')}
                                            className="inline-flex items-center gap-1 px-3 py-1.5 text-xs border rounded-lg bg-white"
                                        >
                                            <Copy size={14} />
                                            {copiedKey === 'live-link' ? text.copied : text.copy}
                                        </button>
                                    </div>
                                </div>
                            </div>
                        ) : (
                            <div className="flex-1 h-full rounded-xl border border-dashed border-slate-200 p-5 flex items-center justify-center">
                                <p className="text-sm text-slate-500 leading-relaxed text-center">{text.resultEmpty}</p>
                            </div>
                        )}
                    </div>
                </form>
            </div>

            <div className="surface-panel rounded-xl p-6 md:p-8">
                <div className="mb-4 flex items-center justify-between gap-4">
                    <div>
                        <h3 className="text-base font-semibold text-slate-900">{text.history}</h3>
                        <p className="text-sm text-slate-500 mt-1">{text.historyHint}</p>
                    </div>
                    <button
                        type="button"
                        onClick={() => setHistory(readLocalHistory())}
                        className="text-sm px-3 py-1.5 border rounded-lg"
                    >
                        {text.refresh}
                    </button>
                </div>
                {history.length === 0 ? (
                    <p className="text-sm text-slate-500">{text.historyEmpty}</p>
                ) : (
                    <div className="space-y-3">
                        {history.map((item) => {
                            const isExpanded = selectedId === item.id;
                            const timeText = item.createdAt
                                ? new Date(item.createdAt).toLocaleString()
                                : '';
                            return (
                                <div
                                    key={item.id}
                                    className={`border rounded-xl p-4 text-sm transition-colors ${
                                        isExpanded ? 'border-slate-400 bg-slate-50/80' : 'border-slate-200'
                                    }`}
                                >
                                    <button
                                        type="button"
                                        onClick={() => toggleRecord(item.id)}
                                        className="w-full text-left cursor-pointer"
                                    >
                                        <div className="flex flex-wrap justify-between gap-2">
                                            <span className="text-slate-500">{timeText || item.id}</span>
                                            <span className="font-medium text-emerald-700">{text.statusDone}</span>
                                        </div>
                                        <p className="mt-2 text-xs text-slate-600">
                                            {isExpanded ? text.hideLink : text.viewLink}
                                        </p>
                                    </button>
                                    {isExpanded && (
                                        <div className="mt-3 pt-3 border-t border-slate-200 space-y-2">
                                            <a
                                                href={item.long_url}
                                                target="_blank"
                                                rel="noreferrer"
                                                className="block text-xs break-all text-emerald-700 hover:underline"
                                            >
                                                {item.long_url}
                                            </a>
                                            <button
                                                type="button"
                                                onClick={() => copyText(item.long_url, `hist-${item.id}`)}
                                                className="inline-flex items-center gap-1 px-2 py-1 text-xs border rounded-lg bg-white"
                                            >
                                                <Copy size={14} />
                                                {copiedKey === `hist-${item.id}` ? text.copied : text.copy}
                                            </button>
                                        </div>
                                    )}
                                </div>
                            );
                        })}
                    </div>
                )}
            </div>
        </div>
    );
}
