from flask import Flask, jsonify, request
import yfinance as yf
import os
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

@app.route('/')
def home():
    return jsonify(message="Hello from Vercel‑deployed Flask app!")

@app.route('/price')
def price():
    """Return the latest close price for a ticker passed as `symbol` query param.
    Example: /price?symbol=MSFT
    """
    symbol = request.args.get('symbol', default='AAPL', type=str)
    ticker = yf.Ticker(symbol)
    # Get live price (using info dict, fallback to last close)
    data = ticker.info
    price = data.get('regularMarketPrice') or data.get('previousClose')
    if price is None:
        return jsonify(error="Could not retrieve price for symbol"), 400
    return jsonify(symbol=symbol.upper(), price=price)

if __name__ == '__main__':
    # Vercel provides the port via the PORT env var
    port = int(os.getenv('PORT', 3000))
    app.run(host='0.0.0.0', port=port)
