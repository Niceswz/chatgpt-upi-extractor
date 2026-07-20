from __future__ import annotations
import base64
import json
import os
import random
import re
import threading
import time
import uuid
from typing import Any
from urllib.parse import parse_qsl, quote, urlencode, urljoin, urlparse
from curl_cffi import requests as curl_requests
try:
    import fcntl
except ImportError:
    fcntl = None
CHECKOUT_REGION = 'IN'
PROMOTION_REGION = 'VN'
PROVIDER_REGION = 'IN'
APPROVE_REGION = 'IN'
MAX_APPROVE_ATTEMPTS = 6
MAX_REBUILD_ATTEMPTS = 2
AMOUNT_POLICY_MAX = 50000
IN_CHROME_PROFILES = ({'impersonate': 'chrome136', 'major': 136, 'build': 7103, 'patch_range': (48, 175), 'sec_ch_ua': '"Chromium";v="136", "Google Chrome";v="136", "Not.A/Brand";v="99"'}, {'impersonate': 'chrome131', 'major': 131, 'build': 6778, 'patch_range': (69, 205), 'sec_ch_ua': '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"'})
IN_ACCEPT_LANGUAGE = 'en-IN,en;q=0.9,hi;q=0.8'
IN_BROWSER_LOCALE = 'en-IN'
VN_ACCEPT_LANGUAGE = 'vi-VN,vi;q=0.9,en;q=0.8'
VN_BROWSER_LOCALE = 'vi-VN'
HUMAN_DELAY_SHORT = (0.8, 1.8)
HUMAN_DELAY_MED = (1.5, 3.2)
HUMAN_DELAY_LONG = (2.5, 5.0)
REGION_HANDOFF_DELAY = (3.5, 6.5)
CHATGPT_CLIENT_VERSION = 'prod-db390ebea64862bf1899c420a4c736e0cf639747'
CHATGPT_CLIENT_BUILD = '7904904'
STRIPE_VERSION = '2025-03-31.basil; checkout_server_update_beta=v1; checkout_manual_approval_preview=v1'
STRIPE_RUNTIME_VERSION = '6f8494a281'
UPI_BILLING_NAME = 'Raj Kumar'
UPI_BILLING_LINE1 = '123 MG Road'
UPI_BILLING_CITY = 'Mumbai'
UPI_BILLING_STATE = 'MH'
UPI_BILLING_POSTAL = '400001'
UPI_PROMO_COUPON = 'plus-1-month-free'
DEFAULT_LOCAL_PROXY = ""
UPI_SCHEME_RE = re.compile('upi://pay[^\\s\\"\'<>]*', re.I)
STRIPE_HOSTED_RE = re.compile('https://hooks\\.stripe\\.com/redirect/[^\\s\\"\'<>]+', re.I)
STRIPE_UPI_INSTRUCTIONS_RE = re.compile('https://payments\\.stripe\\.com/upi/instructions/[^\\s\\"\'<>]+', re.I)
SESSION_COOKIE_NAMES = ('__Secure-next-auth.session-token', 'next-auth.session-token')
_JOB_LOCK = threading.Lock()
_JOBS: dict[str, dict[str, Any]] = {}
_JOB_TTL_SEC = 3600
UPI_JOB_STALE_SEC = 360
MAX_REDIRECT_POLL_ATTEMPTS = 15
APPROVED_REDIRECT_POLL_ATTEMPTS = 20
UPI_EXTRACT_CONCURRENCY = 1
UPI_EXTRACT_QUEUE_WAIT_SEC = 600

def _extract_lock_path() -> str:
    return os.path.join(_jobs_dir(), '.global-extract.lock')

def _queue_state_path() -> str:
    return os.path.join(_jobs_dir(), '.queue-state.json')

def _read_queue_state() -> dict[str, Any]:
    path = _queue_state_path()
    if not os.path.isfile(path):
        return {'active_job_id': '', 'waiting': []}
    try:
        with open(path, encoding='utf-8') as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            return {'active_job_id': '', 'waiting': []}
        waiting = [str(x).strip() for x in data.get('waiting') or [] if str(x).strip()]
        return {'active_job_id': str(data.get('active_job_id') or '').strip(), 'waiting': waiting}
    except Exception:
        return {'active_job_id': '', 'waiting': []}

def _write_queue_state(state: dict[str, Any]) -> None:
    path = _queue_state_path()
    tmp = f'{path}.tmp'
    payload = {'active_job_id': str(state.get('active_job_id') or '').strip(), 'waiting': [str(x).strip() for x in state.get('waiting') or [] if str(x).strip()], 'updated_at': time.time()}
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(payload, fh, ensure_ascii=False)
    os.replace(tmp, path)

def _queue_register_waiting(job_id: str) -> None:
    jid = str(job_id or '').strip()
    if not jid:
        return
    with _JOB_LOCK:
        state = _read_queue_state()
        waiting = [x for x in state.get('waiting') or [] if x != jid]
        waiting.append(jid)
        state['waiting'] = waiting
        _write_queue_state(state)

def _queue_set_active(job_id: str) -> None:
    jid = str(job_id or '').strip()
    if not jid:
        return
    with _JOB_LOCK:
        state = _read_queue_state()
        state['waiting'] = [x for x in state.get('waiting') or [] if x != jid]
        state['active_job_id'] = jid
        _write_queue_state(state)

def _queue_unregister(job_id: str) -> None:
    jid = str(job_id or '').strip()
    if not jid:
        return
    with _JOB_LOCK:
        state = _read_queue_state()
        state['waiting'] = [x for x in state.get('waiting') or [] if x != jid]
        if str(state.get('active_job_id') or '') == jid:
            state['active_job_id'] = ''
        _write_queue_state(state)

def get_upi_queue_snapshot(job_id: str='') -> dict[str, Any]:
    jid = str(job_id or '').strip()
    state = _read_queue_state()
    active = str(state.get('active_job_id') or '').strip()
    waiting = list(state.get('waiting') or [])
    running_count = 1 if active else 0
    queue_size = running_count + len(waiting)
    if jid and jid == active:
        return {'queue_status': 'running', 'queue_ahead': 0, 'queue_size': queue_size}
    if jid and jid in waiting:
        idx = waiting.index(jid)
        ahead = idx + (1 if active else 0)
        return {'queue_status': 'queued', 'queue_ahead': ahead, 'queue_size': queue_size}
    if jid:
        job = _get_job(jid) or {}
        out = job.get('output') if isinstance(job.get('output'), dict) else {}
        steps = out.get('steps') if isinstance(out.get('steps'), list) else []
        for step in reversed(steps):
            if not isinstance(step, dict):
                continue
            if str(step.get('name') or '') == 'queue wait' and str(step.get('status') or '') == 'queued':
                return {'queue_status': 'queued', 'queue_ahead': max(1, queue_size - 1) if queue_size > 0 else 1, 'queue_size': queue_size}
            if str(step.get('name') or '') == 'queue wait' and str(step.get('status') or '') == 'ok':
                break
    return {'queue_status': 'running' if active and (not jid) else '', 'queue_ahead': 0, 'queue_size': queue_size}

def _acquire_extract_slot(job_id: str) -> int:
    if fcntl is None:
        return -1
    if UPI_EXTRACT_CONCURRENCY != 1:
        return -1
    path = _extract_lock_path()
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 420)
    deadline = time.time() + UPI_EXTRACT_QUEUE_WAIT_SEC
    queued = False
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if queued:
                _persist_job_progress(job_id, steps=[{'name': 'queue wait', 'status': 'ok', 'detail': 'Extract slot acquired; starting'}], status='processing')
            return fd
        except BlockingIOError:
            if not queued:
                queued = True
                _persist_job_progress(job_id, steps=[{'name': 'queue wait', 'status': 'queued', 'detail': 'Another extraction is running; queued (1 concurrent account max)'}], status='processing')
            if time.time() >= deadline:
                os.close(fd)
                raise RuntimeError('extract queue timeout: another extraction is still running; retry later')
            time.sleep(2.0)

def _release_extract_slot(fd: int) -> None:
    if fd < 0 or fcntl is None:
        return
    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        try:
            os.close(fd)
        except OSError:
            pass

def _recover_stale_job(job: dict[str, Any]) -> dict[str, Any]:
    if str(job.get('status') or '') != 'processing':
        return job
    updated = float(job.get('updated_at') or job.get('created_at') or 0)
    if not updated or time.time() - updated < UPI_JOB_STALE_SEC:
        return job
    jid = str(job.get('job_id') or '').strip()
    reason = 'Job timed out. Please obtain a fresh Session and retry.'
    steps: list[dict[str, str]] = []
    out = job.get('output')
    if isinstance(out, dict) and isinstance(out.get('steps'), list):
        steps = out.get('steps') or []
    try:
        from .upi_link_admin_service import finalize_upi_link_record
        finalize_upi_link_record(jid, status='failed', result_message=reason, result_message_raw=reason, steps_json=json.dumps(steps, ensure_ascii=False), fail_stage='stale_timeout')
    except Exception:
        pass
    stale = dict(job)
    stale['status'] = 'failed'
    stale['error'] = reason
    stale['updated_at'] = time.time()
    _set_job(stale)
    return stale

def recover_stale_upi_records(max_age_sec: int | None=None) -> int:
    age = int(max_age_sec or UPI_JOB_STALE_SEC)
    reason = 'Job timed out. Please obtain a fresh Session and retry.'
    n = 0
    try:
        from .db import get_primary_db
        from .upi_link_admin_service import finalize_upi_link_record
        with get_primary_db() as c:
            rows = c.execute(
                "SELECT job_id FROM upi_link_extractions "
                "WHERE status = ? AND updated_at < datetime('now', ?)",
                ('processing', f'-{age} seconds'),
            ).fetchall()
        for row in rows:
            jid = str(row['job_id'] or '').strip()
            if not jid:
                continue
            job = _get_job(jid) or {}
            updated = float(job.get('updated_at') or job.get('created_at') or 0)
            if updated and time.time() - updated < age:
                continue
            steps: list[dict[str, str]] = []
            out = job.get('output')
            if isinstance(out, dict) and isinstance(out.get('steps'), list):
                steps = out.get('steps') or []
            finalize_upi_link_record(jid, status='failed', result_message=reason, result_message_raw=reason, steps_json=json.dumps(steps, ensure_ascii=False), fail_stage='stale_timeout')
            _patch_job(jid, status='failed', error=reason)
            _queue_unregister(jid)
            n += 1
    except Exception:
        pass
    return n

def _jobs_dir() -> str:
    path = os.path.join(_project_root(), 'run-output', 'upi-link-jobs')
    os.makedirs(path, exist_ok=True)
    return path

def _job_file(job_id: str) -> str:
    safe = re.sub('[^a-f0-9]', '', str(job_id or '').lower())
    if not safe:
        safe = 'invalid'
    return os.path.join(_jobs_dir(), f'{safe}.json')

def _read_job_file(job_id: str) -> dict[str, Any] | None:
    path = _job_file(job_id)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding='utf-8') as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else None
    except Exception:
        return None

def _write_job_file(job: dict[str, Any]) -> None:
    job_id = str(job.get('job_id') or '').strip()
    if not job_id:
        return
    path = _job_file(job_id)
    tmp = f'{path}.tmp'
    payload = json.dumps(job, ensure_ascii=False)
    with open(tmp, 'w', encoding='utf-8') as fh:
        fh.write(payload)
    os.replace(tmp, path)

def _get_job(job_id: str) -> dict[str, Any] | None:
    with _JOB_LOCK:
        job = _JOBS.get(job_id) or _read_job_file(job_id)
        if job:
            _JOBS[job_id] = job
        return job

def _set_job(job: dict[str, Any]) -> None:
    job_id = str(job.get('job_id') or '').strip()
    if not job_id:
        return
    with _JOB_LOCK:
        _JOBS[job_id] = job
        _write_job_file(job)

def _patch_job(job_id: str, **fields: Any) -> dict[str, Any]:
    with _JOB_LOCK:
        job = dict(_JOBS.get(job_id) or _read_job_file(job_id) or {'job_id': job_id})
        job.update(fields)
        job['updated_at'] = time.time()
        _JOBS[job_id] = job
        _write_job_file(job)
        return job

def _project_root() -> str:
    return str(os.environ.get('VERIFY_APP_ROOT') or os.environ.get('APP_ROOT') or '').strip() or os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

def _debug_dir() -> str:
    path = os.path.join(_project_root(), 'run-output', 'upi-link-debug')
    os.makedirs(path, exist_ok=True)
    return path

def _mask_proxy_summary(proxy: str) -> str:
    text = str(proxy or '').strip()
    if not text:
        return ''
    if '@' in text:
        scheme, rest = text.split('://', 1) if '://' in text else ('', text)
        creds, host = rest.rsplit('@', 1)
        user = creds.split(':', 1)[0]
        masked_user = user[:4] + '***' if len(user) > 4 else '***'
        return f'{scheme}://{masked_user}:***@{host}' if scheme else f'{masked_user}:***@{host}'
    return text[:24] + '...' if len(text) > 24 else text

def _proxy_with_fresh_sid(proxy: str) -> str:
    proxy = str(proxy or '').strip()
    if not proxy:
        return proxy
    return re.sub('sid-[^-:@]*-t-', f'sid-{uuid.uuid4().hex[:8]}-t-', proxy)

def _infer_fail_stage(steps: list[dict[str, str]], error: str) -> str:
    err = str(error or '').lower()
    if steps:
        last = str(steps[-1].get('name') or '')
        if last:
            return last
    if '401' in err or 'token_revoked' in err or 'oauth token' in err:
        return 'checkout_auth'
    if 'approve' in err:
        return 'approve'
    if 'redirect' in err or 'poll' in err:
        return 'stripe_redirect_poll'
    if 'amount policy' in err or 'promo' in err:
        return 'promotion_amount'
    if 'stale' in err or 'timeout' in err:
        return 'stale_timeout'
    if 'checkout' in err:
        return 'checkout'
    return 'unknown'

def _write_debug_artifact(job_id: str, payload: dict[str, Any]) -> None:
    jid = re.sub('[^a-f0-9]', '', str(job_id or '').lower())
    if not jid:
        return
    path = os.path.join(_debug_dir(), f'{jid}.json')
    tmp = f'{path}.tmp'
    body = json.dumps(payload, ensure_ascii=False, indent=2)
    try:
        with open(tmp, 'w', encoding='utf-8') as fh:
            fh.write(body)
        os.replace(tmp, path)
    except Exception:
        pass

def _persist_job_progress(job_id: str, *, steps: list[dict[str, str]], status: str='processing', error: str='', debug: dict[str, Any] | None=None) -> None:
    jid = str(job_id or '').strip()
    if not jid:
        return
    from .portal_tools_service import sanitize_upi_extract_message
    safe_error = sanitize_upi_extract_message(error)
    safe_steps = []
    for item in steps:
        safe = dict(item)
        safe['detail'] = sanitize_upi_extract_message(safe.get('detail'))
        safe_steps.append(safe)
    _patch_job(jid, status=status, error=safe_error, output={'steps': safe_steps})
    _write_debug_artifact(jid, {'job_id': jid, 'status': status, 'error': safe_error, 'steps': safe_steps, 'debug': debug or {}, 'updated_at': time.time()})

def _load_env_file() -> None:
    path = os.path.join(_project_root(), 'env_upi_link.txt')
    if not os.path.isfile(path):
        return
    try:
        with open(path, encoding='utf-8') as fh:
            for raw in fh:
                line = raw.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                key, value = line.split('=', 1)
                key = key.strip()
                if not key.startswith('UPI_LINK_'):
                    continue
                val = value.strip().strip('"').strip("'")
                if val and (not str(os.environ.get(key) or '').strip()):
                    os.environ[key] = val
    except Exception:
        pass


def save_upi_proxies(india_proxy: str, promotion_proxy: str) -> None:
    """Persist UPI proxy settings to env_upi_link.txt and update os.environ.

    This writes only the two proxy variables and leaves other env entries untouched.
    """
    try:
        path = os.path.join(_project_root(), 'env_upi_link.txt')
        lines = []
        if os.path.isfile(path):
            try:
                with open(path, encoding='utf-8') as fh:
                    for raw in fh:
                        line = raw.rstrip('\n')
                        if not line or line.strip().startswith('#') or '=' not in line:
                            lines.append(line)
                            continue
                        key = line.split('=', 1)[0].strip()
                        if key in ('UPI_LINK_PROXY', 'UPI_LINK_PROMOTION_PROXY'):
                            # skip existing, we'll write updated below
                            continue
                        lines.append(line)
            except Exception:
                lines = []
        # append updated proxy lines
        if india_proxy is None:
            india_proxy = ''
        if promotion_proxy is None:
            promotion_proxy = ''
        lines.append(f'UPI_LINK_PROXY={india_proxy}')
        lines.append(f'UPI_LINK_PROMOTION_PROXY={promotion_proxy}')
        # atomic write
        tmp = f'{path}.tmp'
        with open(tmp, 'w', encoding='utf-8') as fh:
            fh.write('\n'.join(lines) + '\n')
        os.replace(tmp, path)
        # update environment for current process
        if india_proxy is not None:
            os.environ['UPI_LINK_PROXY'] = str(india_proxy or '').strip()
        if promotion_proxy is not None:
            os.environ['UPI_LINK_PROMOTION_PROXY'] = str(promotion_proxy or '').strip()
    except Exception:
        # best-effort; do not raise
        pass

def resolve_upi_proxy() -> str:
    _load_env_file()
    for key in ('UPI_LINK_PROXY', 'OPENAI_PAY_DEFAULT_PROXY'):
        val = str(os.environ.get(key) or '').strip()
        if val:
            return val
    return DEFAULT_LOCAL_PROXY

def _load_chatgpt_rt_env_file() -> None:
    path = os.path.join(_project_root(), 'env_chatgpt_rt.txt')
    if not os.path.isfile(path):
        return
    try:
        with open(path, encoding='utf-8') as fh:
            for raw in fh:
                line = raw.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                key, value = line.split('=', 1)
                key = key.strip()
                if not key.startswith('CHATGPT_RT_'):
                    continue
                val = value.strip().strip('"').strip("'")
                if val and (not str(os.environ.get(key) or '').strip()):
                    os.environ[key] = val
    except Exception:
        pass

def _parse_rt_proxy_line(raw_line: str) -> str:
    text = str(raw_line or '').strip()
    if not text:
        return ''
    if '://' in text:
        return text
    parts = text.split(':')
    if len(parts) >= 4:
        host, port, user = (parts[0], parts[1], parts[2])
        password = ':'.join(parts[3:])
        user_q = quote(user, safe='')
        pass_q = quote(password, safe='')
        return f'http://{user_q}:{pass_q}@{host}:{port}'
    if len(parts) == 2:
        return f'http://{parts[0]}:{parts[1]}'
    return ''

def _rt_proxy_from_env() -> str:
    _load_chatgpt_rt_env_file()
    direct = str(os.environ.get('CHATGPT_RT_PROXY') or '').strip()
    if direct:
        return direct
    line = str(os.environ.get('CHATGPT_RT_PROXY_LINE') or '').strip()
    if line:
        return _parse_rt_proxy_line(line)
    return ''

def resolve_upi_promotion_proxy(base_proxy: str='') -> str:
    _load_env_file()
    dedicated = str(os.environ.get('UPI_LINK_PROMOTION_PROXY') or '').strip()
    if dedicated:
        return proxy_for_region(dedicated, PROMOTION_REGION) or dedicated
    base = str(base_proxy or resolve_upi_proxy()).strip()
    return proxy_for_region(base, PROMOTION_REGION) if base else ''

def _uses_lowercase_proxy_region(proxy: str) -> bool:
    text = str(proxy or '').strip().lower()
    return 'iproyal' in text or ('://' not in text and text.count(':') >= 4)

def proxy_for_region(proxy: str, region: str) -> str:
    proxy = str(proxy or '').strip()
    region = str(region or '').strip()
    if not proxy or not region:
        return proxy
    region_val = region.lower() if _uses_lowercase_proxy_region(proxy) else region.upper()
    rewritten = re.sub('region-[A-Za-z]{2}', f'region-{region_val}', proxy)
    if region.upper() != 'JP':
        rewritten = re.sub('-st-[^-:@]+-sid-', '-sid-', rewritten)
    return rewritten

def normalize_access_token(raw: str) -> str:
    text = str(raw or '').strip()
    if text.lower().startswith('bearer '):
        text = text[7:].strip()
    if not text:
        return ''
    if text.startswith('{') or text.startswith('['):
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return ''
        return _find_token(data) or ''
    return text

def _parse_session_object(raw: str) -> dict[str, Any]:
    text = str(raw or '').strip()
    if not text.startswith('{'):
        return {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}

def _extract_session_token_from_raw(raw: str) -> str:
    return str(_parse_session_object(raw).get('sessionToken') or '').strip()

def _refresh_access_token_from_session(session_token: str, proxy: str, device_id: str) -> str:
    from curl_cffi import requests as cr
    token = str(session_token or '').strip()
    if not token:
        return ''
    proxy_url = str(proxy or '').strip()
    session = cr.Session(impersonate='chrome131')
    session.trust_env = False
    for name in SESSION_COOKIE_NAMES:
        try:
            session.cookies.set(name, token, domain='chatgpt.com', path='/')
        except Exception:
            pass
    try:
        r = session.get('https://chatgpt.com/api/auth/session', headers={'Accept': 'application/json', 'Referer': 'https://chatgpt.com/', 'Origin': 'https://chatgpt.com', 'oai-device-id': device_id}, proxies={'http': proxy_url, 'https': proxy_url} if proxy_url else None, timeout=30)
        if r.status_code != 200:
            return ''
        data = r.json() if r.text else {}
        if not isinstance(data, dict):
            return ''
        return str(data.get('accessToken') or '').strip()
    except Exception:
        return ''
    finally:
        session.close()

def resolve_upi_access_token(raw: str, proxy: str='') -> str:
    token = normalize_access_token(raw)
    if not token:
        return ''
    proxy_url = str(proxy or resolve_upi_proxy() or '').strip()
    if not proxy_url:
        return token
    client = UpiHttpClient(proxy_url, region='IN')
    try:
        st, _, _ = client.request('GET', 'https://chatgpt.com/backend-api/me', headers=_chatgpt_headers(client, token), proxy=proxy_url)
        if st == 200:
            return token
        session_token = _extract_session_token_from_raw(raw)
        if not session_token:
            return token
        fresh = _refresh_access_token_from_session(session_token, proxy_url, client.device_id)
        if not fresh:
            return token
        st2, _, _ = client.request('GET', 'https://chatgpt.com/backend-api/me', headers=_chatgpt_headers(client, fresh), proxy=proxy_url)
        return fresh if st2 == 200 else token
    finally:
        client.close()

def _find_token(value: Any) -> str | None:
    if isinstance(value, str):
        token = normalize_access_token(value)
        return token or None
    if isinstance(value, list):
        for item in value:
            found = _find_token(item)
            if found:
                return found
        return None
    if isinstance(value, dict):
        for key in ('accessToken', 'access_token', 'token'):
            if key in value:
                found = _find_token(value.get(key))
                if found:
                    return found
        for item in value.values():
            found = _find_token(item)
            if found:
                return found
    return None

def _jwt_payload(token: str) -> dict[str, Any]:
    try:
        payload = token.split('.')[1]
        pad = '=' * (-len(payload) % 4)
        data = json.loads(base64.urlsafe_b64decode(payload + pad))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}

def _jwt_account_id(token: str) -> str:
    auth = _jwt_payload(token).get('https://api.openai.com/auth') or {}
    if isinstance(auth, dict):
        return str(auth.get('chatgpt_account_id') or '').strip()
    return ''

def _jwt_email(token: str) -> str:
    data = _jwt_payload(token)
    if not data:
        return 'buyer@example.com'
    profile = data.get('https://api.openai.com/profile') or {}
    if isinstance(profile, dict):
        email = str(profile.get('email') or profile.get('email_address') or '').strip()
        if '@' in email:
            return email
    email = str(data.get('email') or data.get('preferred_username') or '').strip()
    return email if '@' in email else 'buyer@example.com'

def _fetch_promo_coupon_state(token: str, proxy: str) -> str:
    client = _spawn_region_client(proxy, 'VN')
    try:
        headers = _chatgpt_headers(client, token, promotion=True)
        account_id = _jwt_account_id(token)
        if account_id:
            headers['ChatGPT-Account-Id'] = account_id
        promo_proxy = client.base_proxy or resolve_upi_promotion_proxy(proxy)
        url = f'https://chatgpt.com/backend-api/promo_campaign/check_coupon?coupon={UPI_PROMO_COUPON}&is_coupon_from_query_param=true'
        status, text, _ = client.request('GET', url, headers=headers, proxy=promo_proxy)
        if status >= 400:
            return 'unknown'
        try:
            data = json.loads(text or '{}')
        except json.JSONDecodeError:
            return 'unknown'
        if not isinstance(data, dict):
            return 'unknown'
        state = str(data.get('state') or '').strip().lower()
        if state == 'eligible':
            return 'eligible'
        redemption = data.get('redemption') if isinstance(data.get('redemption'), dict) else {}
        if redemption.get('redeemed_by_user') or redemption.get('redeemed'):
            return 'already_redeemed'
        if state in ('not_eligible', 'ineligible'):
            return 'not_eligible'
        return state or 'unknown'
    finally:
        client.close()

def _assert_upi_promo_eligible(token: str, proxy: str) -> None:
    state = _fetch_promo_coupon_state(token, proxy)
    if state in ('eligible', 'unknown'):
        return
    if state == 'already_redeemed':
        raise RuntimeError('upi promo already redeemed')
    raise RuntimeError(f'upi promo not eligible: state={state}')

def _pick_india_chrome_profile() -> dict[str, Any]:
    order = list(IN_CHROME_PROFILES)
    random.shuffle(order)
    last_err: Exception | None = None
    for profile in order:
        name = str(profile['impersonate'])
        try:
            curl_requests.Session(impersonate=name)
            return profile
        except Exception as exc:
            last_err = exc
            continue
    fallback = {'impersonate': 'chrome124', 'major': 124, 'build': 6367, 'patch_range': (60, 207), 'sec_ch_ua': '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"'}
    try:
        curl_requests.Session(impersonate='chrome124')
        return fallback
    except Exception as exc:
        raise RuntimeError(f'curl_cffi has no usable Chrome impersonate profile: {last_err or exc}') from exc

class UpiHttpClient:

    def __init__(self, proxy: str, *, region: str='IN'):
        self.base_proxy = str(proxy or '').strip()
        self.proxy = self.base_proxy
        self.region = str(region or 'IN').upper()
        profile = _pick_india_chrome_profile()
        major = int(profile['major'])
        build = int(profile['build'])
        patch = random.randint(*profile['patch_range'])
        self.chrome_full = f'{major}.0.{build}.{patch}'
        self.impersonate = str(profile['impersonate'])
        self.ua = f'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{self.chrome_full} Safari/537.36'
        self.sec_ch_ua = str(profile['sec_ch_ua'])
        self.sec_ch_ua_platform = '"Windows"'
        if self.region == 'VN':
            self.accept_language = VN_ACCEPT_LANGUAGE
            self.locale = VN_BROWSER_LOCALE
        else:
            self.accept_language = IN_ACCEPT_LANGUAGE
            self.locale = IN_BROWSER_LOCALE
        self.device_id = str(uuid.uuid4())
        self.session = curl_requests.Session(impersonate=self.impersonate)
        self.session.trust_env = False
        self.session.headers.update(self._browser_headers())
        self.session.cookies.set('oai-did', self.device_id, domain='chatgpt.com')
        self.session.cookies.set('oai-did', self.device_id, domain='.chatgpt.com')
        self._apply_proxy(self.base_proxy)

    def close(self) -> None:
        try:
            self.session.close()
        except Exception:
            pass

    def _browser_headers(self) -> dict[str, str]:
        return {'User-Agent': self.ua, 'Accept-Language': self.accept_language, 'sec-ch-ua': self.sec_ch_ua, 'sec-ch-ua-mobile': '?0', 'sec-ch-ua-platform': self.sec_ch_ua_platform, 'sec-ch-ua-full-version': f'"{self.chrome_full}"'}

    def _apply_proxy(self, proxy: str | None) -> str:
        effective = str(proxy or self.base_proxy or '').strip()
        self.proxy = effective
        if effective:
            self.session.proxies.update({'http': effective, 'https': effective})
        else:
            self.session.proxies.clear()
        return effective

    def request(self, method: str, url: str, *, headers: dict[str, str] | None=None, json_body: dict | None=None, form: dict[str, str] | None=None, timeout: float=45.0, allow_redirects: bool=False, proxy: str | None=None) -> tuple[int, str, dict[str, str]]:
        self._apply_proxy(proxy)
        hdrs = dict(headers or {})
        try:
            resp = self.session.request(method.upper(), url, headers=hdrs, json=json_body, data=form, timeout=timeout, allow_redirects=allow_redirects, impersonate=self.impersonate)
            return (resp.status_code, resp.text or '', {k.lower(): v for k, v in resp.headers.items()})
        except Exception as exc:
            raise RuntimeError(f'Network request failed ({self.impersonate}): {exc}') from exc

def _human_pause(kind: str='med') -> None:
    spans = {'short': HUMAN_DELAY_SHORT, 'med': HUMAN_DELAY_MED, 'long': HUMAN_DELAY_LONG, 'handoff': REGION_HANDOFF_DELAY}
    low, high = spans.get(kind, HUMAN_DELAY_MED)
    time.sleep(random.uniform(low, high))

def _chatgpt_headers(client: UpiHttpClient, token: str, *, promotion: bool=False) -> dict[str, str]:
    accept_language = VN_ACCEPT_LANGUAGE if promotion else client.accept_language
    browser_locale = VN_BROWSER_LOCALE if promotion else client.locale
    return {'user-agent': client.ua, 'accept': '*/*', 'accept-language': accept_language, 'authorization': f'Bearer {token}', 'origin': 'https://chatgpt.com', 'referer': 'https://chatgpt.com/', 'content-type': 'application/json', 'oai-device-id': client.device_id, 'oai-language': browser_locale, 'oai-session-id': str(uuid.uuid4()), 'oai-client-version': CHATGPT_CLIENT_VERSION, 'oai-client-build-number': CHATGPT_CLIENT_BUILD, 'sec-ch-ua': client.sec_ch_ua, 'sec-ch-ua-mobile': '?0', 'sec-ch-ua-platform': client.sec_ch_ua_platform, 'sec-fetch-dest': 'empty', 'sec-fetch-mode': 'cors', 'sec-fetch-site': 'same-origin', 'cookie': f'oai-did={client.device_id}'}

def _spawn_region_client(base_proxy: str, region: str, *, fresh_sid: bool=False) -> UpiHttpClient:
    region = str(region or 'IN').upper()
    if region == 'VN':
        proxy = resolve_upi_promotion_proxy(base_proxy)
    else:
        proxy = proxy_for_region(base_proxy, region) or base_proxy
        if fresh_sid:
            proxy = _proxy_with_fresh_sid(proxy)
    return UpiHttpClient(proxy, region=region)

def _warmup_india_client(client: UpiHttpClient, token: str, proxy: str) -> None:
    headers = _chatgpt_headers(client, token)
    try:
        client.request('POST', 'https://chatgpt.com/backend-api/sentinel/ping', headers=_target_headers(headers, '/backend-api/sentinel/ping', 'https://chatgpt.com/'), json_body={}, proxy=proxy, timeout=20.0)
    except Exception:
        pass

def _target_headers(base: dict[str, str], path: str, referer: str) -> dict[str, str]:
    hdrs = dict(base)
    hdrs['referer'] = referer
    hdrs['x-openai-target-path'] = path
    hdrs['x-openai-target-route'] = path
    return hdrs

def _stripe_headers(client: UpiHttpClient) -> dict[str, str]:
    return {'user-agent': client.ua, 'accept-language': client.accept_language, 'origin': 'https://js.stripe.com', 'referer': 'https://js.stripe.com/', 'sec-ch-ua': client.sec_ch_ua, 'sec-ch-ua-mobile': '?0', 'sec-ch-ua-platform': client.sec_ch_ua_platform}

def _import_build_sentinel_token():
    """Optional OpenAI sentinel helper. Missing module is non-fatal."""
    try:
        from .chatgpt_rt_oauth.core.direct_protocol import build_sentinel_token
        return build_sentinel_token
    except ImportError:
        pass
    try:
        from chatgpt_rt_oauth.core.direct_protocol import build_sentinel_token
        return build_sentinel_token
    except ImportError:
        return None

def _attach_approve_sentinel(client: UpiHttpClient, headers: dict[str, str]) -> dict[str, str]:
    out = dict(headers)
    try:
        build_sentinel_token = _import_build_sentinel_token()
        if build_sentinel_token is None:
            out['_upi_sentinel_error'] = 'optional chatgpt_rt_oauth module not installed'
            return out
        for flow in ('authorize_continue', 'checkout_pay', 'checkout_approve'):
            token = build_sentinel_token(client.session, client.device_id, flow=flow, user_agent=client.ua, sec_ch_ua=client.sec_ch_ua, impersonate=client.impersonate, sec_ch_ua_platform=client.sec_ch_ua_platform, accept_language=client.accept_language, locale=client.locale)
            if token:
                out['openai-sentinel-token'] = token
                out['_upi_sentinel_flow'] = flow
                break
    except Exception as exc:
        out['_upi_sentinel_error'] = str(exc)[:240]
    return out

def _first_string(data: Any, keys: list[str]) -> str:
    if not isinstance(data, dict):
        return ''
    for key in keys:
        val = data.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ''

def _expected_amount(payload: dict) -> int:
    due = payload.get('total_summary', {}).get('due') if isinstance(payload.get('total_summary'), dict) else None
    if due is not None:
        try:
            return int(due)
        except (TypeError, ValueError):
            pass
    invoice = payload.get('invoice', {})
    if isinstance(invoice, dict) and invoice.get('amount_due') is not None:
        try:
            return int(invoice['amount_due'])
        except (TypeError, ValueError):
            pass
    total = 0
    found = False
    for item in payload.get('line_items') or []:
        if isinstance(item, dict) and item.get('amount') is not None:
            try:
                total += int(item['amount'])
                found = True
            except (TypeError, ValueError):
                pass
    return total if found else 0

def _payment_method_types(payload: dict) -> list[str]:
    methods: list[str] = []

    def push(val: Any) -> None:
        if isinstance(val, str):
            m = val.strip().lower()
            if m and m not in methods:
                methods.append(m)
        elif isinstance(val, list):
            for item in val:
                push(item)
        elif isinstance(val, dict) and isinstance(val.get('type'), str):
            push(val['type'])
    push(payload.get('payment_method_types'))
    return methods

def _ensure_upi_offered(payload: dict, phase: str) -> None:
    methods = _payment_method_types(payload)
    if 'upi' not in methods:
        raise RuntimeError(f"{phase} checkout does not offer upi (India-only); methods={','.join(methods) or 'none'}; need Indian egress proxy (region-IN) for checkout/provider stages")

def _json_or_error(status: int, text: str, label: str) -> dict:
    if status >= 400:
        preview = (text or '')[:240]
        raise RuntimeError(f'{label} failed: HTTP {status} {preview}')
    try:
        data = json.loads(text or '{}')
    except json.JSONDecodeError as exc:
        raise RuntimeError(f'{label} invalid JSON') from exc
    if not isinstance(data, dict):
        raise RuntimeError(f'{label} unexpected response')
    return data

def _is_upi_url(url: str) -> bool:
    u = str(url or '').strip()
    if u.lower().startswith('upi://'):
        return True
    try:
        parsed = urlparse(u)
        host = (parsed.hostname or '').lower()
        path = parsed.path or ''
        if host == 'hooks.stripe.com' and path.startswith('/redirect/'):
            return True
        if 'stripe.com' in host and ('upi' in path or path.startswith('/redirect/')):
            return True
    except Exception:
        return False
    return False

def _extract_upi_from_text(text: str) -> str:
    for regex in (UPI_SCHEME_RE, STRIPE_UPI_INSTRUCTIONS_RE, STRIPE_HOSTED_RE):
        m = regex.search(text or '')
        if m and _is_upi_url(m.group(0)):
            return m.group(0)
    return ''

def _payment_page_poll_summary(payload: Any) -> str:
    if not isinstance(payload, dict):
        return str(payload or '')[:180]
    keys = ','.join(list(payload.keys())[:8])
    state = payload.get('state')
    submission = payload.get('submission_attempt')
    if not state and isinstance(submission, dict):
        state = submission.get('state')
    status = payload.get('status') or payload.get('payment_status')
    setup_intent = payload.get('setup_intent')
    if not status and isinstance(setup_intent, dict):
        status = setup_intent.get('status')
    return f"keys=[{keys}]; state={state or '-'}; status={status or '-'}"

def _find_upi_action_url(value: Any) -> str:
    if isinstance(value, dict):
        na = value.get('next_action') or {}
        if isinstance(na, dict):
            upi = na.get('upi_handle_redirect_or_display_qr_code') or {}
            if isinstance(upi, dict):
                hosted = str(upi.get('hosted_instructions_url') or '').strip()
                if hosted:
                    return hosted
                qr = str((upi.get('qr_code') or {}).get('data') or '').strip()
                if qr.startswith('upi://'):
                    return qr
            redirect = na.get('redirect_to_url') or {}
            if isinstance(redirect, dict):
                url = str(redirect.get('url') or '').strip()
                if _is_upi_url(url):
                    return url
        for key in ('url', 'redirect_url', 'hosted_url'):
            url = str(value.get(key) or '').strip()
            if _is_upi_url(url):
                return url
        for item in value.values():
            found = _find_upi_action_url(item)
            if found:
                return found
    elif isinstance(value, list):
        for item in value:
            found = _find_upi_action_url(item)
            if found:
                return found
    elif isinstance(value, str):
        return _extract_upi_from_text(value)
    return ''

def _extract_redirect_url(payload: Any) -> str:
    if isinstance(payload, dict):
        found = _find_upi_action_url(payload)
        if found:
            return found
        na = payload.get('next_action') or {}
        if isinstance(na, dict):
            redirect = na.get('redirect_to_url') or {}
            if isinstance(redirect, dict):
                url = str(redirect.get('url') or '').strip()
                if url:
                    return url
        for item in payload.values():
            found = _extract_redirect_url(item)
            if found:
                return found
    elif isinstance(payload, list):
        for item in payload:
            found = _extract_redirect_url(item)
            if found:
                return found
    elif isinstance(payload, str):
        return _extract_upi_from_text(payload)
    return ''

def _confirm_requires_approval(payload: dict) -> bool:
    return str((payload.get('submission_attempt') or {}).get('state') or '') == 'requires_approval'

def _chatgpt_success_return_url(cs_id: str, processor_entity: str) -> str:
    return f'https://chatgpt.com/checkout/success?processor_entity={processor_entity}&checkout_session_id={cs_id}'

def _stripe_confirm_return_url(cs_id: str, processor_entity: str, stripe_hosted_url: str) -> str:
    hosted = stripe_hosted_url.strip() or f'https://checkout.stripe.com/c/pay/{cs_id}'
    parsed = urlparse(hosted)
    if parsed.hostname not in ('pay.openai.com', 'checkout.stripe.com'):
        return hosted
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    if 'success_return_url' not in query:
        query['success_return_url'] = _chatgpt_success_return_url(cs_id, processor_entity)
    new_query = urlencode(query)
    return parsed._replace(query=new_query).geturl()

def _stripe_poll_form(stripe_pk: str) -> dict[str, str]:
    return {'elements_session_client[client_betas][0]': 'custom_checkout_server_updates_1', 'elements_session_client[client_betas][1]': 'custom_checkout_manual_approval_1', 'elements_session_client[elements_init_source]': 'custom_checkout', 'elements_session_client[referrer_host]': 'chatgpt.com', 'elements_session_client[session_id]': f'elements_session_{uuid.uuid4().hex[:11]}', 'elements_session_client[stripe_js_id]': str(uuid.uuid4()), 'elements_session_client[locale]': 'en', 'elements_session_client[is_aggregation_expected]': 'false', 'elements_options_client[saved_payment_method][enable_save]': 'never', 'elements_options_client[saved_payment_method][enable_redisplay]': 'never', 'key': stripe_pk, '_stripe_version': STRIPE_VERSION}

def _stripe_init_form(stripe_pk: str) -> dict[str, str]:
    form = _stripe_poll_form(stripe_pk)
    form['browser_locale'] = 'en-IN'
    form['browser_timezone'] = 'Asia/Kolkata'
    return form

def extract_upi_link(access_token: str, proxy: str | None=None, *, job_id: str='', on_step: Any=None) -> dict[str, Any]:
    proxy_url = str(proxy or resolve_upi_proxy() or '').strip()
    if not proxy_url:
        raise RuntimeError('proxy is required for UPI extraction')
    raw_session = str(access_token or '').strip()
    orig_token = normalize_access_token(raw_session)
    token = resolve_upi_access_token(raw_session, proxy_url)
    if not token:
        raise ValueError('Access Token is required')
    steps: list[dict[str, str]] = []
    last_error: Exception | None = None

    def step(name: str, status: str, detail: str) -> None:
        steps.append({'name': name, 'status': status, 'detail': detail})
        if callable(on_step):
            try:
                on_step(list(steps))
            except Exception:
                pass
    if token != orig_token:
        step('session refresh', 'ok', 'accessToken refreshed via sessionToken')
    for attempt in range(1, MAX_REBUILD_ATTEMPTS + 1):
        if attempt > 1:
            step('rebuild checkout', 'info', f'attempt {attempt}/{MAX_REBUILD_ATTEMPTS}')
        client = UpiHttpClient(proxy_url, region='IN')
        try:
            result = _run_upi_attempt(client, token, step, steps)
            result['steps'] = steps
            return result
        except Exception as exc:
            last_error = exc
            detail = str(exc)
            if 'blocked by risk control' in detail.lower():
                raise
            if not _is_rebuild_retryable(exc) or attempt >= MAX_REBUILD_ATTEMPTS:
                raise
            step('rebuild retry', 'warn', detail)
            _human_pause('long')
        finally:
            try:
                client.close()
            except Exception:
                pass
    raise last_error or RuntimeError('extract failed after rebuild retries')

def _run_upi_attempt(client: UpiHttpClient, token: str, step: Any, steps: list[dict[str, str]]) -> dict[str, Any]:
    india_base = client.base_proxy
    checkout_proxy = proxy_for_region(india_base, CHECKOUT_REGION) or india_base
    headers = _chatgpt_headers(client, token)
    step('browser fingerprint', 'ok', f'IN chrome TLS={client.impersonate}; ua=Chrome/{client.chrome_full}; locale={client.locale}; did={client.device_id[:8]}')
    _human_pause('short')
    checkout_body = {'entry_point': 'all_plans_pricing_modal', 'plan_name': 'chatgptplusplan', 'billing_details': {'country': 'IN', 'currency': 'INR'}, 'promo_campaign': {'promo_campaign_id': 'plus-1-month-free', 'is_coupon_from_query_param': False}, 'checkout_ui_mode': 'custom'}
    ch = dict(headers)
    ch['x-openai-target-path'] = '/backend-api/payments/checkout'
    ch['x-openai-target-route'] = '/backend-api/payments/checkout'
    status, text, _ = client.request('POST', 'https://chatgpt.com/backend-api/payments/checkout', headers=ch, json_body=checkout_body, proxy=checkout_proxy)
    checkout = _json_or_error(status, text, 'checkout create')
    cs_id = _first_string(checkout, ['checkout_session_id', 'session_id', 'id'])
    if not cs_id.startswith('cs_'):
        raise RuntimeError(f'checkout missing cs_id: {text[:200]}')
    processor_entity = _first_string(checkout, ['processor_entity', 'processorEntity']) or 'openai_ie'
    stripe_pk = _first_string(checkout, ['publishable_key']) or ''
    step('checkout', 'ok', f'IN bootstrap cs={cs_id}')
    _human_pause('med')

    def stripe_init(active: UpiHttpClient, proxy: str) -> dict:
        form = _stripe_init_form(stripe_pk)
        st, body, _ = active.request('POST', f'https://api.stripe.com/v1/payment_pages/{cs_id}/init', headers=_stripe_headers(active), form=form, proxy=proxy)
        data = _json_or_error(st, body, 'stripe init')
        hosted = _first_string(data, ['stripe_hosted_url'])
        if not hosted:
            raise RuntimeError('stripe init missing stripe_hosted_url')
        data['_stripe_hosted_url'] = hosted
        return data
    init = stripe_init(client, checkout_proxy)
    _ensure_upi_offered(init, 'IN bootstrap')
    step('stripe init', 'ok', f"amount={_expected_amount(init)}; methods={','.join(_payment_method_types(init))}")
    _human_pause('med')
    vn_client = _spawn_region_client(india_base, 'VN')
    promotion_proxy = vn_client.base_proxy or resolve_upi_promotion_proxy(india_base)
    promo_headers = _chatgpt_headers(vn_client, token, promotion=True)
    step('VN promo fingerprint', 'ok', f'VN chrome TLS={vn_client.impersonate}; locale={vn_client.locale}; did={vn_client.device_id[:8]}; proxy={_mask_proxy_summary(promotion_proxy)}')
    _human_pause('short')
    referer = f'https://chatgpt.com/checkout/{processor_entity}/{cs_id}'
    promo_body = {'checkout_session_id': cs_id, 'processor_entity': processor_entity, 'plan_name': 'chatgptplusplan', 'price_interval': 'month', 'seat_quantity': 1, 'promo_campaign': {'promo_campaign_id': 'plus-1-month-free', 'is_coupon_from_query_param': False}}
    try:
        st, text, _ = vn_client.request('POST', 'https://chatgpt.com/backend-api/payments/checkout/update', headers=_target_headers(promo_headers, '/backend-api/payments/checkout/update', referer), json_body=promo_body, proxy=promotion_proxy)
        promo = _json_or_error(st, text, 'checkout promotion update')
        if promo.get('success') is False:
            raise RuntimeError(f'promotion update rejected: {text[:200]}')
        step('VN promotion update', 'ok', 'checkout/update via VN IP + vi-VN succeeded')
    finally:
        vn_client.close()
    step('region handoff', 'info', 'cooling down after VN promo; spawning fresh India identity')
    _human_pause('handoff')
    client.close()
    india = _spawn_region_client(india_base, 'IN', fresh_sid=True)
    try:
        return _run_upi_india_phase(india, token=token, step=step, steps=steps, cs_id=cs_id, processor_entity=processor_entity, stripe_pk=stripe_pk, stripe_init=stripe_init, referer=referer, india_base=india_base)
    finally:
        india.close()

def _run_upi_india_phase(client: UpiHttpClient, *, token: str, step: Any, steps: list[dict[str, str]], cs_id: str, processor_entity: str, stripe_pk: str, stripe_init: Any, referer: str, india_base: str) -> dict[str, Any]:
    provider_proxy = client.base_proxy or proxy_for_region(india_base, PROVIDER_REGION) or india_base
    approve_proxy = proxy_for_region(india_base, APPROVE_REGION) or provider_proxy
    headers = _chatgpt_headers(client, token)
    step('IN reentry fingerprint', 'ok', f'IN chrome TLS={client.impersonate}; locale={client.locale}; did={client.device_id[:8]}; proxy={_mask_proxy_summary(provider_proxy)}')
    _warmup_india_client(client, token, provider_proxy)
    step('IN reentry warmup', 'ok', 'sentinel/ping on new India IP')
    _human_pause('med')
    init = stripe_init(client, provider_proxy)
    amount = _expected_amount(init)
    _ensure_upi_offered(init, 'IN reentry after VN promo')
    if amount > AMOUNT_POLICY_MAX:
        raise RuntimeError(f'upi promo not eligible: amount policy failed after promotion: amount={amount}')
    step('IN reentry Stripe init', 'ok', f'amount={amount}')
    _human_pause('med')
    email = _jwt_email(token)
    taxes_body = {'checkout_session_id': cs_id, 'checkout_email': email, 'billing_country': 'IN', 'billing_name': UPI_BILLING_NAME, 'currency': 'INR', 'tax_id': None, 'processor_entity': processor_entity, 'billing_address': {'line1': UPI_BILLING_LINE1, 'city': UPI_BILLING_CITY, 'state': UPI_BILLING_STATE, 'country': 'IN', 'postal_code': UPI_BILLING_POSTAL}}
    client.request('POST', 'https://chatgpt.com/backend-api/payments/checkout/taxes', headers=_target_headers(headers, '/backend-api/payments/checkout/taxes', referer), json_body=taxes_body, proxy=provider_proxy)
    step('UPI ChatGPT taxes', 'ok', 'country=IN')
    _human_pause('short')
    tax_form = {'eid': 'NA', 'tax_region[country]': 'IN', 'tax_region[postal_code]': UPI_BILLING_POSTAL, 'tax_region[line1]': UPI_BILLING_LINE1, 'tax_region[city]': UPI_BILLING_CITY, 'tax_region[state]': UPI_BILLING_STATE, 'key': stripe_pk}
    client.request('POST', f'https://api.stripe.com/v1/payment_pages/{cs_id}', headers=_stripe_headers(client), form=tax_form, proxy=provider_proxy)
    step('UPI Stripe tax region', 'ok', 'country=IN')
    _human_pause('short')
    init = stripe_init(client, provider_proxy)
    amount = _expected_amount(init)
    _ensure_upi_offered(init, 'tax refresh')
    if amount > AMOUNT_POLICY_MAX:
        raise RuntimeError(f'upi promo not eligible: amount policy failed after tax sync: amount={amount}')
    step('UPI tax Stripe init', 'ok', f'amount={amount}')
    _human_pause('med')
    pm_form = {'billing_details[name]': UPI_BILLING_NAME, 'billing_details[email]': email, 'billing_details[address][country]': 'IN', 'billing_details[address][line1]': UPI_BILLING_LINE1, 'billing_details[address][city]': UPI_BILLING_CITY, 'billing_details[address][state]': UPI_BILLING_STATE, 'billing_details[address][postal_code]': UPI_BILLING_POSTAL, 'type': 'upi', 'client_attribution_metadata[checkout_session_id]': cs_id, 'key': stripe_pk}
    st, text, _ = client.request('POST', 'https://api.stripe.com/v1/payment_methods', headers=_stripe_headers(client), form=pm_form, proxy=provider_proxy)
    pm = _json_or_error(st, text, 'stripe payment_methods')
    pm_id = _first_string(pm, ['id'])
    if not pm_id.startswith('pm_'):
        raise RuntimeError('stripe payment_methods bad response')
    step('payment method', 'ok', pm_id)
    _human_pause('long')
    sid = uuid.uuid4().hex
    confirm_form = {'eid': 'NA', 'payment_method': pm_id, 'expected_amount': str(amount), 'expected_payment_method_type': 'upi', 'return_url': _stripe_confirm_return_url(cs_id, processor_entity, init.get('_stripe_hosted_url', '')), '_stripe_version': STRIPE_VERSION, 'guid': sid, 'muid': sid, 'sid': sid, 'key': stripe_pk, 'version': STRIPE_RUNTIME_VERSION, 'init_checksum': _first_string(init, ['init_checksum']), 'client_attribution_metadata[client_session_id]': str(uuid.uuid4()), 'client_attribution_metadata[checkout_session_id]': cs_id, 'client_attribution_metadata[merchant_integration_source]': 'checkout', 'client_attribution_metadata[merchant_integration_version]': 'custom_checkout', 'client_attribution_metadata[payment_method_selection_flow]': 'automatic', 'client_attribution_metadata[checkout_config_id]': _first_string(init, ['config_id']), 'link_brand': 'link'}
    st, text, _ = client.request('POST', f'https://api.stripe.com/v1/payment_pages/{cs_id}/confirm', headers=_stripe_headers(client), form=confirm_form, proxy=provider_proxy)
    confirm = _json_or_error(st, text, 'stripe confirm')
    step('stripe confirm', 'ok', 'completed')
    _human_pause('long')
    stripe_redirect = _extract_redirect_url(confirm) or _extract_upi_from_text(text)
    if not stripe_redirect and _confirm_requires_approval(confirm):
        approve_body = {'checkout_session_id': cs_id, 'processor_entity': processor_entity}
        approve_headers = _target_headers(headers, '/backend-api/payments/checkout/approve', referer)
        approved = False
        last_approve_detail = ''
        for i in range(1, MAX_APPROVE_ATTEMPTS + 1):
            current_approve_proxy = approve_proxy if i == 1 else _proxy_with_fresh_sid(approve_proxy)
            _human_pause('short' if i == 1 else 'med')
            client.request('POST', 'https://chatgpt.com/backend-api/sentinel/ping', headers=_target_headers(headers, '/backend-api/sentinel/ping', 'https://chatgpt.com/'), json_body={}, proxy=current_approve_proxy)
            _human_pause('short')
            current_approve_headers = _attach_approve_sentinel(client, approve_headers)
            sentinel_flow = str(current_approve_headers.pop('_upi_sentinel_flow', '') or '')
            sentinel_err = str(current_approve_headers.pop('_upi_sentinel_error', '') or '')
            has_sentinel = bool(current_approve_headers.get('openai-sentinel-token'))
            step('approve sentinel', 'ok' if has_sentinel else 'warn', f"attached flow={sentinel_flow}; len={len(current_approve_headers.get('openai-sentinel-token') or '')}" if has_sentinel else f"missing sentinel; err={sentinel_err or 'empty token'}")
            if i > 1:
                step('approve retry', 'info', f'attempt {i}/{MAX_APPROVE_ATTEMPTS}; fresh sid + sentinel')
            st, text, _ = client.request('POST', 'https://chatgpt.com/backend-api/payments/checkout/approve', headers=current_approve_headers, json_body=approve_body, proxy=current_approve_proxy)
            payload = _json_or_error(st, text, 'chatgpt approve')
            result = _first_string(payload, ['result', 'status', 'state'])
            last_approve_detail = f"result={result or 'empty'}; body={text[:240]}"
            if result == 'approved':
                step('approve', 'ok', f'attempt {i}/{MAX_APPROVE_ATTEMPTS}')
                polled = _poll_upi_redirect_after_approve(client, cs_id, stripe_pk, steps, provider_proxy, step)
                if polled:
                    stripe_redirect = polled
                    approved = True
                    break
                raise RuntimeError('approved but redirect not ready after polling; rebuilding checkout from start')
            step('approve response', 'warn' if result == 'blocked' else 'info', last_approve_detail)
            if result == 'blocked':
                raise RuntimeError('chatgpt approve blocked by risk control: result=blocked')
            quick_url = _poll_stripe_redirect(client, cs_id, stripe_pk, steps, provider_proxy, max_attempts=2, sleep_sec=0.8, quiet=True)
            if quick_url:
                stripe_redirect = quick_url
                approved = True
                step('approve poll shortcut', 'ok', 'redirect ready before approve succeeded')
                break
            time.sleep(1.0)
        if not approved:
            raise RuntimeError(f'chatgpt approve failed after retries: {last_approve_detail}')
    if not stripe_redirect:
        stripe_redirect = _poll_stripe_redirect(client, cs_id, stripe_pk, steps, provider_proxy)
    long_url = _resolve_external_redirect(client, stripe_redirect, provider_proxy) or stripe_redirect
    step('provider redirect', 'ok', long_url)
    return {'success': True, 'ok': True, 'long_url': long_url, 'cs_id': cs_id, 'billing_country': 'IN', 'currency': 'INR', 'payment_method_id': pm_id, 'amount': amount}

def _is_rebuild_retryable(exc: Exception) -> bool:
    detail = str(exc).lower()
    if 'blocked by risk control' in detail or 'result=blocked' in detail:
        return False
    if 'network request failed' in detail or 'proxy connect' in detail or 'curl:' in detail:
        return False
    if 'amount policy' in detail:
        return True
    if 'redirect not ready' in detail or 'redirect url resolution' in detail:
        return True
    return any((code in detail for code in ('502', '503', '504')))

def _poll_upi_redirect_after_approve(client: UpiHttpClient, cs_id: str, stripe_pk: str, steps: list[dict[str, str]], provider_proxy: str, step: Any) -> str:
    url = _poll_stripe_redirect(client, cs_id, stripe_pk, steps, provider_proxy, max_attempts=APPROVED_REDIRECT_POLL_ATTEMPTS, sleep_sec=1.0)
    if url:
        return url
    step('stripe redirect wait', 'info', f'phase1={APPROVED_REDIRECT_POLL_ATTEMPTS} done; polling up to {MAX_REDIRECT_POLL_ATTEMPTS} more on same cs')
    return _poll_stripe_redirect(client, cs_id, stripe_pk, steps, provider_proxy, max_attempts=MAX_REDIRECT_POLL_ATTEMPTS, sleep_sec=1.2)

def _poll_stripe_redirect(client: UpiHttpClient, cs_id: str, stripe_pk: str, steps: list[dict[str, str]], provider_proxy: str, *, max_attempts: int | None=None, sleep_sec: float=1.2, quiet: bool=False) -> str:
    form = _stripe_poll_form(stripe_pk)
    last_summary = ''
    attempts = int(max_attempts or MAX_REDIRECT_POLL_ATTEMPTS)
    for attempt in range(1, attempts + 1):
        st, text, _ = client.request('GET', f'https://api.stripe.com/v1/payment_pages/{cs_id}', headers=_stripe_headers(client), form=form, proxy=provider_proxy)
        payload = _json_or_error(st, text, 'stripe payment_pages poll')
        url = _extract_redirect_url(payload) or _extract_upi_from_text(text)
        if url:
            return url
        last_summary = _payment_page_poll_summary(payload)
        if attempt < attempts:
            if not quiet:
                steps.append({'name': 'stripe redirect retry', 'status': 'info', 'detail': f'attempt {attempt}/{attempts}; redirect not ready ({last_summary})'})
            time.sleep(max(0.4, random.uniform(sleep_sec * 0.7, sleep_sec * 1.6)))
    if quiet:
        return ''
    raise RuntimeError(f'redirect url resolution timeout after {attempts} poll(s): {last_summary}')

def _resolve_external_redirect(client: UpiHttpClient, redirect_url: str, provider_proxy: str) -> str:
    current = str(redirect_url or '').strip()
    for _ in range(5):
        if not current:
            break
        if _is_upi_url(current):
            return current
        st, text, hdrs = client.request('GET', current, headers=_stripe_headers(client), allow_redirects=False, proxy=provider_proxy)
        try:
            body_json = json.loads(text) if text.strip().startswith('{') else {}
        except json.JSONDecodeError:
            body_json = {}
        found = _extract_upi_from_text(text) or _find_upi_action_url(body_json)
        if found:
            return found
        location = hdrs.get('location', '')
        if st in (301, 302, 303, 307, 308) and location:
            current = urljoin(current, location)
            if _is_upi_url(current):
                return current
            continue
        break
    return ''

def _run_job(job_id: str, access_token: str, proxy: str, user_id: str) -> None:
    from .upi_link_admin_service import finalize_upi_link_record
    from .portal_tools_service import sanitize_upi_extract_message
    promo_proxy = resolve_upi_promotion_proxy(proxy)
    debug_ctx = {'checkout_region': CHECKOUT_REGION, 'promotion_region': PROMOTION_REGION, 'provider_region': PROVIDER_REGION, 'india_proxy': _mask_proxy_summary(proxy_for_region(proxy, CHECKOUT_REGION)), 'promotion_proxy': _mask_proxy_summary(promo_proxy), 'tls_impersonate': 'chrome-in', 'human_delay': True}
    steps_snapshot: list[dict[str, str]] = []

    def step_hook(steps: list[dict[str, str]]) -> None:
        nonlocal steps_snapshot
        steps_snapshot = steps
        _persist_job_progress(job_id, steps=steps, debug=debug_ctx)
    lock_fd = -1
    _queue_register_waiting(job_id)
    try:
        lock_fd = _acquire_extract_slot(job_id)
        _queue_set_active(job_id)
        output = extract_upi_link(access_token, proxy=proxy, job_id=job_id, on_step=step_hook)
        steps = output.get('steps') or steps_snapshot
        finalize_upi_link_record(job_id, status='completed', long_url=str(output.get('long_url') or '').strip(), currency=str(output.get('currency') or 'INR'), result_message='', steps_json=json.dumps(steps, ensure_ascii=False), debug_json=json.dumps({**debug_ctx, 'amount': output.get('amount')}, ensure_ascii=False), amount=output.get('amount'))
        _write_debug_artifact(job_id, {'job_id': job_id, 'status': 'completed', 'steps': steps, 'debug': debug_ctx, 'output': output, 'updated_at': time.time()})
        _patch_job(job_id, status='completed', output=output, error='')
    except Exception as exc:
        job = _get_job(job_id) or {}
        steps = steps_snapshot or ((job.get('output') or {}).get('steps') if isinstance(job.get('output'), dict) else []) or []
        raw = sanitize_upi_extract_message(exc)
        fail_stage = _infer_fail_stage(steps, raw)
        finalize_upi_link_record(job_id, status='failed', result_message=raw, result_message_raw=raw, steps_json=json.dumps(steps, ensure_ascii=False), debug_json=json.dumps(debug_ctx, ensure_ascii=False), fail_stage=fail_stage)
        _write_debug_artifact(job_id, {'job_id': job_id, 'status': 'failed', 'error': raw, 'fail_stage': fail_stage, 'steps': steps, 'debug': debug_ctx, 'updated_at': time.time()})
        _patch_job(job_id, status='failed', error=raw, output={'steps': steps})
    finally:
        _release_extract_slot(lock_fd)
        _queue_unregister(job_id)

def start_upi_link_extract(access_token: str, *, user_id: str='') -> dict[str, Any]:
    from .upi_link_admin_service import insert_upi_link_record
    raw_session = str(access_token or '').strip()
    proxy = resolve_upi_proxy()
    token = resolve_upi_access_token(raw_session, proxy)
    if not token:
        return {'success': False, 'error': 'Please paste a valid accessToken or session JSON'}
    email = _jwt_email(token)
    promo_state = _fetch_promo_coupon_state(token, proxy)
    try:
        _assert_upi_promo_eligible(token, proxy)
    except Exception as exc:
        fail_id = uuid.uuid4().hex
        insert_upi_link_record(job_id=fail_id, user_id=user_id, email=email, promo_state=promo_state, status='failed', result_message=str(exc), result_message_raw=str(exc), fail_stage='precheck')
        return {'success': False, 'error': str(exc)}
    job_id = uuid.uuid4().hex
    now = time.time()
    insert_upi_link_record(job_id=job_id, user_id=user_id, email=email, promo_state=promo_state, status='processing', debug_json=json.dumps({'checkout_region': CHECKOUT_REGION, 'promotion_region': PROMOTION_REGION, 'india_proxy': _mask_proxy_summary(proxy_for_region(proxy, CHECKOUT_REGION)), 'promotion_proxy': _mask_proxy_summary(resolve_upi_promotion_proxy(proxy))}, ensure_ascii=False))
    _set_job({'job_id': job_id, 'status': 'processing', 'user_id': str(user_id or ''), 'error': '', 'output': None, 'created_at': now, 'updated_at': now})
    threading.Thread(target=_run_job, args=(job_id, raw_session, proxy, user_id), daemon=True, name=f'upi-link-{job_id[:8]}').start()
    return {'success': True, 'job_id': job_id, 'status': 'processing', **get_upi_queue_snapshot(job_id)}

def get_upi_link_status(job_id: str, *, user_id: str='') -> dict[str, Any]:
    jid = str(job_id or '').strip()
    if not jid:
        return {'success': False, 'error': 'Missing job_id'}
    job = _get_job(jid)
    if not job:
        return {'success': False, 'error': 'Job not found or expired'}
    job = _recover_stale_job(job)
    created = float(job.get('created_at') or 0)
    if created and time.time() - created > _JOB_TTL_SEC:
        return {'success': False, 'error': 'Job not found or expired'}
    owner = str(job.get('user_id') or '')
    if owner and user_id and (owner != str(user_id)):
        return {'success': False, 'error': 'Job not found or expired'}
    status = str(job.get('status') or 'processing')
    from .portal_tools_service import sanitize_upi_extract_message
    payload: dict[str, Any] = {'success': True, 'job_id': jid, 'status': status, 'error': sanitize_upi_extract_message(job.get('error'))}
    if status == 'processing':
        payload.update(get_upi_queue_snapshot(jid))
    output = job.get('output')
    if isinstance(output, dict):
        payload['long_url'] = output.get('long_url') or ''
        payload['currency'] = output.get('currency') or 'INR'
        payload['steps'] = output.get('steps') if isinstance(output.get('steps'), list) else []
    return payload
