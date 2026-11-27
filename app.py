from flask import Flask, Response, jsonify, request
import json
import os
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import yfinance as yf
from flask_cors import CORS

app = Flask(__name__)
CORS(app)


def _normalize_symbol(raw_symbol: str) -> str:
    symbol = (raw_symbol or 'MARKET').strip().upper()
    if symbol in ('MARKET', 'INDIA', 'NSE', 'ALL'):
        return 'MARKET'
    if symbol and '.' not in symbol and '^' not in symbol:
        symbol = f'{symbol}.NS'
    return symbol or 'MARKET'


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


def _fetch_google_news_rss(query_text: str, symbol_label: str, limit: int = 12) -> list[dict]:
    query = urllib.parse.quote(query_text)
    url = f'https://news.google.com/rss/search?q={query}&hl=en-IN&gl=IN&ceid=IN:en'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=6) as resp:
        xml_bytes = resp.read()
    root = ET.fromstring(xml_bytes)
    items = []
    for idx, elem in enumerate(root.findall('./channel/item')[:limit]):
        title = (elem.findtext('title') or '').strip()
        link = (elem.findtext('link') or '').strip()
        pub_date = (elem.findtext('pubDate') or '').strip()
        source_el = elem.find('source')
        publisher = source_el.text.strip() if source_el is not None and source_el.text else 'Google News'
        if not title:
            continue
        items.append({
            'id': f'{symbol_label}-rss-{idx}',
            'symbol': symbol_label,
            'title': title,
            'link': link,
            'publisher': publisher,
            'pubDate': pub_date,
        })
    return items


def _extract_news(symbol: str) -> list[dict]:
    if symbol == 'MARKET':
        seen_titles = set()
        merged = []
        for idx_sym in ('^NSEI', '^BSESN', 'RELIANCE.NS', 'TCS.NS', 'HDFCBANK.NS'):
            try:
                for item in _fetch_yfinance_news(idx_sym):
                    key = item['title'].strip().lower()
                    if key not in seen_titles:
                        seen_titles.add(key)
                        merged.append(item)
            except Exception:
                continue
        if len(merged) < 8:
            try:
                for item in _fetch_google_news_rss('Nifty 50 Sensex NSE Indian stock market', 'MARKET', limit=15):
                    key = item['title'].strip().lower()
                    if key not in seen_titles:
                        seen_titles.add(key)
                        merged.append(item)
            except Exception:
                pass
        return merged[:20]

    try:
        items = _fetch_yfinance_news(symbol)
        if items:
            return items
    except Exception:
        pass
    base_name = symbol.split('.')[0]
    return _fetch_google_news_rss(f'{base_name} NSE stock', symbol)


@app.route('/')
def home():
    return jsonify(message="Hello from Vercel-deployed Flask app!")


@app.route('/price')
def price():
    """Return the latest close price for a ticker passed as `symbol` query param."""
    symbol = request.args.get('symbol', default='AAPL', type=str)
    ticker = yf.Ticker(symbol)
    data = ticker.info
    latest_price = data.get('regularMarketPrice') or data.get('previousClose')
    if latest_price is None:
        return jsonify(error="Could not retrieve price for symbol"), 400
    return jsonify(symbol=symbol.upper(), price=latest_price)


@app.route('/news')
def news():
    """Return normalized news headlines as JSON for a ticker."""
    symbol = _normalize_symbol(request.args.get('symbol', default='RELIANCE.NS', type=str))
    try:
        items = _extract_news(symbol)
        return jsonify(symbol=symbol, count=len(items), items=items)
    except Exception as exc:
        return jsonify(error=str(exc), symbol=symbol), 500


@app.route('/news-sse')
def news_sse():
    """Stream normalized news headlines over Server-Sent Events (SSE)."""
    symbol = _normalize_symbol(request.args.get('symbol', default='RELIANCE.NS', type=str))

    def generate():
        yield "retry: 15000\n\n"
        try:
            items = _extract_news(symbol)
            if not items:
                payload = json.dumps({
                    'id': f'{symbol}-empty',
                    'symbol': symbol,
                    'title': f'No recent headlines found for {symbol}.',
                    'link': f'https://finance.yahoo.com/quote/{symbol}/news',
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
