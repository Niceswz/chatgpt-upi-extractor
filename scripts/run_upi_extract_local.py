from __future__ import annotations
import argparse
import json
import os
import sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(ROOT, 'api_python'))
from upi_link_service import extract_upi_link, resolve_upi_access_token, resolve_upi_proxy

def main() -> int:
    parser = argparse.ArgumentParser(description='Local UPI link extract test')
    parser.add_argument('--session-file', required=True, help='Path to session JSON file')
    parser.add_argument('--proxy', default='', help='Override UPI_LINK_PROXY')
    args = parser.parse_args()
    raw = open(args.session_file, encoding='utf-8').read()
    token = resolve_upi_access_token(raw)
    if not token:
        print('ERROR: no valid accessToken in session file', file=sys.stderr)
        return 1
    proxy = (args.proxy or resolve_upi_proxy()).strip()
    print(f'proxy={proxy}')
    print('extracting…')
    try:
        result = extract_upi_link(raw, proxy=proxy)
    except Exception as exc:
        print(f'FAILED: {exc}', file=sys.stderr)
        return 2
    print(json.dumps({'success': result.get('success'), 'long_url': result.get('long_url'), 'cs_id': result.get('cs_id'), 'amount': result.get('amount'), 'steps_count': len(result.get('steps') or [])}, ensure_ascii=False, indent=2))
    return 0 if result.get('long_url') else 3
if __name__ == '__main__':
    raise SystemExit(main())
