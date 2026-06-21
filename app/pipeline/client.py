"""
The REST client the pipeline uses to read prod's event stream.

It does bulk, cursor-based reads. The cursor is currently the event timestamp,
expressed through prod's existing `dateFrom` filter so it works against the live
API with no server changes; a cleaner `?since=<id>` path is stubbed in for the
day prod exposes a proper id cursor.

A single keep-alive session is reused across calls, and the auth token is cached
and transparently refreshed whenever a request comes back 401.
"""
import os
import time
import requests

PROD_API_BASE = os.environ.get('VEX_PROD_API_BASE', 'https://inviteinstitutehub.org')
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class ProdClientError(RuntimeError):
    pass


def _credentials():
    user = os.environ.get('PROD_USERNAME')
    pw = os.environ.get('PROD_PASSWORD')
    if user and pw:
        return user, pw
    env_path = os.path.join(_BASE_DIR, '.env.mirror')
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line.startswith('PROD_USERNAME='):
                    user = user or line.split('=', 1)[1]
                elif line.startswith('PROD_PASSWORD='):
                    pw = pw or line.split('=', 1)[1]
    return user, pw


class ProdClient:
    """A thin wrapper over prod's /api/rabbitmq/vex_logs/ endpoint, handling
    token auth, a keep-alive session, and re-auth on a 401."""

    def __init__(self, base=PROD_API_BASE, connect_timeout=3.0, read_timeout=8.0):
        self.base = base
        self.timeout = (connect_timeout, read_timeout)
        self.session = requests.Session()
        self._token = None

    # -- auth -------------------------------------------------------------
    def _authenticate(self):
        user, pw = _credentials()
        if not user or not pw:
            raise ProdClientError("Missing PROD_USERNAME/PROD_PASSWORD (.env.mirror or env).")
        resp = self.session.post(f'{self.base}/api/token/',
                                 json={'username': user, 'password': pw},
                                 timeout=self.timeout)
        if resp.status_code != 200:
            raise ProdClientError(f"Auth failed ({resp.status_code}).")
        self._token = resp.json().get('token')
        return self._token

    def token(self):
        return self._token or self._authenticate()

    # -- reads ------------------------------------------------------------
    def _get(self, params):
        """Fetch one page of results. Retries once after re-authenticating if the
        first attempt returns 401; any other non-200 raises ProdClientError."""
        headers = {'Authorization': f'Token {self.token()}'}
        resp = self.session.get(f'{self.base}/api/rabbitmq/vex_logs/',
                                headers=headers, params=params, timeout=self.timeout)
        if resp.status_code == 401:
            headers = {'Authorization': f'Token {self._authenticate()}'}
            resp = self.session.get(f'{self.base}/api/rabbitmq/vex_logs/',
                                    headers=headers, params=params, timeout=self.timeout)
        if resp.status_code != 200:
            raise ProdClientError(f"prod API {resp.status_code}: {resp.text[:120]}")
        return resp.json().get('results', [])

    def page_by_time(self, date_from_iso, limit, offset):
        """A page of events across all students with received_at >= date_from.
        This is what a normal drain uses."""
        params = {'limit': limit, 'offset': offset}
        if date_from_iso:
            params['dateFrom'] = date_from_iso
        return self._get(params)

    def page_by_id(self, since_id, limit):
        """A page using a proper id cursor (?since). Not used yet; here for when
        prod supports it."""
        return self._get({'since': since_id, 'limit': limit})

    def page_student(self, student_id, limit, offset):
        """A page of one student's events, newest first. Used to backfill a
        student's history when they're added to the roster."""
        return self._get({'studentID': student_id, 'limit': limit, 'offset': offset})
