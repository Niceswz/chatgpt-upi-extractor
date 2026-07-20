/**
 * CSRF-aware POST helper for portal / standalone embeds.
 * Prefers ensureCsrfToken when provided; otherwise uses csrf from headers or cookies.
 */

async function resolveCsrfToken({ ensureCsrfToken, csrfToken }) {
  if (typeof ensureCsrfToken === 'function') {
    const token = await ensureCsrfToken();
    if (token) return String(token);
  }
  if (csrfToken) return String(csrfToken);
  return '';
}

export async function portalCsrfPost({
  apiBase = '',
  path = '',
  body = null,
  fetchOpts,
  ensureCsrfToken,
  onCsrfToken,
  csrfToken = '',
}) {
  const base = String(apiBase || '').replace(/\/$/, '');
  const url = `${base}${path.startsWith('/') ? path : `/${path}`}`;
  const csrf = await resolveCsrfToken({ ensureCsrfToken, csrfToken });

  let opts;
  if (typeof fetchOpts === 'function') {
    opts = fetchOpts('POST', body, false);
  } else {
    opts = {
      method: 'POST',
      credentials: 'include',
      cache: 'no-store',
      headers: { 'Content-Type': 'application/json' },
      body: body == null ? undefined : JSON.stringify(body),
    };
  }

  opts.headers = { ...(opts.headers || {}) };
  if (csrf) {
    opts.headers['X-CSRF-Token'] = csrf;
  }
  if (opts.body == null && body != null && typeof fetchOpts !== 'function') {
    opts.body = JSON.stringify(body);
  }

  const res = await fetch(url, opts);
  let data = {};
  try {
    data = await res.json();
  } catch {
    data = {};
  }

  const nextCsrf = res.headers?.get?.('x-csrf-token') || data?.csrf_token;
  if (nextCsrf && typeof onCsrfToken === 'function') {
    onCsrfToken(String(nextCsrf));
  }

  return { res, data };
}

export default portalCsrfPost;
