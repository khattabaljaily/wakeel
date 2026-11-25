"""Free public sources of exchange rates, each as {currency: units per USD}. Both publish once a day, so a currency whose
market moves within the day (Sudan's) needs a rate set by hand (see ExchangeRate.MANUAL)."""
import json
import logging
import urllib.request
from decimal import Decimal, InvalidOperation

logger = logging.getLogger(__name__)
TIMEOUT = 20


def _get(url):
    request = urllib.request.Request(url, headers={'User-Agent': 'Wakeel exchange rates'})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        return json.loads(response.read().decode('utf-8'))


def _clean(rates):
    out = {}
    for code, value in (rates or {}).items():
        try:
            value = Decimal(str(value))
        except (InvalidOperation, ValueError):
            continue
        if len(code) == 3 and code.isalpha() and value > 0:
            out[code.upper()] = value
    return out


def open_er_api():
    data = _get('https://open.er-api.com/v6/latest/USD')
    return _clean(data.get('rates')) if data.get('result') == 'success' else {}


def currency_api():
    data = _get('https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@latest/v1/currencies/usd.json')
    return _clean(data.get('usd'))


SOURCES = {'open.er-api.com': open_er_api, 'currency-api': currency_api}


def fetch_all():
    """{source name: rates}; a source that fails is left out (and logged)."""
    found = {}
    for name, fetch in SOURCES.items():
        try:
            rates = fetch()
        except Exception as exc:                 # network, JSON, anything: the other source may still answer
            logger.warning('Exchange rate source %s failed: %s', name, exc)
            continue
        if rates:
            found[name] = rates
    return found
