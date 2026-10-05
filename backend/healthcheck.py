"""Docker health check: healthy once Django answers HTTP at all.

/api/auth/me returns 401 without a cookie, which still proves the server
is up, so an HTTP error response counts as healthy. Only a refused or timed
out connection is unhealthy.
"""
import sys
import urllib.error
import urllib.request

try:
    urllib.request.urlopen("http://127.0.0.1:8500/api/auth/me", timeout=3)
except urllib.error.HTTPError:
    pass
except Exception:
    sys.exit(1)
