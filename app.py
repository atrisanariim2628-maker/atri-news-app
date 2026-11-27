from flask import Flask, Response, jsonify, request
import json
import os
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
import yfinance as yf
from flask_cors import CORS

app = Flask(__name__)
CORS(app)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalize_symbol(raw_symbol: str) -> str:
    symbol = (raw_symbol or 'MARKET').strip().upper()
    if symbol in ('MARKET', 'INDIA', 'NSE', 'ALL'):
        return 'MARKET'
    if symbol and '.' not in symbol and '^' not in symbol:
        symbol = f'{symbol}.NS'
    return symbol or 'MARKET'


def _fetch_rss(url: str, symbol_label: str, limit: int = 12) -> list[dict]:
    """Fetch and parse any RSS feed URL."""
    req = urllib.request.Request(url, headers={
        'User-Agent': 'Mozilla/5.0 (compatible; newsbot/1.0)',
        'Accept': 'application/rss+xml, application/xml, text/xml',
    })
    with urllib.request.urlopen(req, timeout=8) as resp:
        xml_bytes = resp.read()
    root = ET.fromstring(xml_bytes)
    items = []
    for idx, elem in enumerate(root.findall('./channel/item')[:limit]):
        title = (elem.findtext('title') or '').strip()
        link = (elem.findtext('link') or '').strip()
        pub_date_str = (elem.findtext('pubDate') or '').strip()
        source_el = elem.find('source')
        publisher = (source_el.text or '').strip() if source_el is not None else ''
        if not publisher:
            # Try to infer from link
            try:
                from urllib.parse import urlparse
                publisher = urlparse(link).netloc.replace('www.', '')
            except Exception:
                publisher = 'Market Wire'
        if not title:
            continue
        items.append({
            'id': f'{symbol_label}-rss-{idx}',
            'symbol': symbol_label,
            'title': title,
            'link': link,
            'publisher': publisher,
            'pubDate': pub_date_str,
        })
    return items


def _fetch_yfinance_news(symbol: str) -> list[dict]:
    ticker = yf.Ticker(symbol)
    raw_items = ticker.news or []
    items = []
    for idx, item in enumerate(raw_items):
        content = item.get('content') if isinstance(item.get('content'), dict) else item
        title = content.get('title') or item.get('title')
        if not title:
            continue
        canonical = content.get('canonicalUrl') if isinstance(content.get('canonicalUrl'), dict) else {}
        click_through = content.get('clickThroughUrl') if isinstance(content.get('clickThroughUrl'), dict) else {}
        provider = content.get('provider') if isinstance(content.get('provider'), dict) else {}
        link = (
            canonical.get('url')
            or click_through.get('url')
            or content.get('link')
            or item.get('link')
            or f'https://finance.yahoo.com/quote/{symbol}/news'
        )
        items.append({
            'id': item.get('id') or content.get('id') or f'{symbol}-{idx}',
            'symbol': symbol,
            'title': title,
            'link': link,
            'publisher': provider.get('displayName') or item.get('publisher') or 'Yahoo Finance',
            'pubDate': content.get('pubDate') or content.get('displayTime') or '',
        })
    return items


# Direct RSS feeds from major Indian financial news publishers
MARKET_RSS_FEEDS = [
    # Moneycontrol - markets section
    ('https://www.moneycontrol.com/rss/marketreports.xml', 'Moneycontrol'),
    # Economic Times - markets
    ('https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms', 'Economic Times'),
    # Mint - markets
    ('https://www.livemint.com/rss/markets', 'Mint'),
    # Business Standard - markets
    ('https://www.business-standard.com/rss/markets-106.rss', 'Business Standard'),
    # NDTV Profit
    ('https://feeds.feedburner.com/ndtvprofit-latest', 'NDTV Profit'),
]


def _extract_market_news() -> list[dict]:
    seen_titles: set[str] = set()
    merged: list[dict] = []

    def _add(items: list[dict]) -> None:
        for item in items:
            key = item['title'].strip().lower()
            if key and key not in seen_titles:
                seen_titles.add(key)
                merged.append(item)

    # Try direct RSS feeds first (freshest)
    for feed_url, label in MARKET_RSS_FEEDS:
        try:
            _add(_fetch_rss(feed_url, label, limit=8))
        except Exception:
            continue
        if len(merged) >= 20:
            break

    # Google News RSS as secondary
    if len(merged) < 15:
        google_queries = [
            ('Nifty Sensex India stock market', 'NSE'),
            ('BSE NSE Indian shares today', 'BSE'),
        ]
        for q, label in google_queries:
            try:
                url = f'https://news.google.com/rss/search?q={urllib.parse.quote(q)}&hl=en-IN&gl=IN&ceid=IN:en'
                _add(_fetch_rss(url, label, limit=10))
            except Exception:
                continue

    # yfinance fallback if still thin
    if len(merged) < 10:
        for sym in ('^NSEI', '^BSESN', 'RELIANCE.NS', 'TCS.NS'):
            try:
                _add(_fetch_yfinance_news(sym))
            except Exception:
                continue

    return merged[:25]


def _extract_news(symbol: str) -> list[dict]:
    if symbol == 'MARKET':
        return _extract_market_news()

    seen_titles: set[str] = set()
    merged: list[dict] = []

    def _add(items: list[dict]) -> None:
        for item in items:
            key = item['title'].strip().lower()
            if key and key not in seen_titles:
                seen_titles.add(key)
                merged.append(item)

    # yfinance first for single stocks (usually fresh enough)
    try:
        _add(_fetch_yfinance_news(symbol))
    except Exception:
        pass

    # Google News RSS backup
    if not merged:
        base = symbol.split('.')[0]
        try:
            url = f'https://news.google.com/rss/search?q={urllib.parse.quote(base + " NSE stock")}&hl=en-IN&gl=IN&ceid=IN:en'
            _add(_fetch_rss(url, symbol, limit=12))
        except Exception:
            pass

    return merged


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route('/')
def home():
    return jsonify(message="Hello from Vercel-deployed Flask app!")


@app.route('/price')
def price():
    symbol = request.args.get('symbol', default='AAPL', type=str)
    ticker = yf.Ticker(symbol)
    data = ticker.info
    latest_price = data.get('regularMarketPrice') or data.get('previousClose')
    if latest_price is None:
        return jsonify(error="Could not retrieve price for symbol"), 400
    return jsonify(symbol=symbol.upper(), price=latest_price)


@app.route('/news')
def news():
    symbol = _normalize_symbol(request.args.get('symbol', default='MARKET', type=str))
    try:
        items = _extract_news(symbol)
        return jsonify(symbol=symbol, count=len(items), items=items)
    except Exception as exc:
        return jsonify(error=str(exc), symbol=symbol), 500


@app.route('/news-sse')
def news_sse():
    symbol = _normalize_symbol(request.args.get('symbol', default='MARKET', type=str))

    def generate():
        yield "retry: 15000\n\n"
        try:
            items = _extract_news(symbol)
            if not items:
                payload = json.dumps({
                    'id': f'{symbol}-empty',
                    'symbol': symbol,
                    'title': f'No recent headlines found for {symbol}.',
                    'link': 'https://www.moneycontrol.com/news/business/markets/',
                    'publisher': 'System',
                    'pubDate': '',
                })
                yield f"data: {payload}\n\n"
                return
            for item in items:
                yield f"id: {item['id']}\ndata: {json.dumps(item)}\n\n"
        except Exception as exc:
            err_payload = json.dumps({'error': str(exc), 'symbol': symbol})
            yield f"event: error\ndata: {err_payload}\n\n"

    return Response(
        generate(),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
            'Access-Control-Allow-Origin': '*',
        },
    )


if __name__ == '__main__':
    port = int(os.getenv('PORT', 3000))
    app.run(host='0.0.0.0', port=port)
