# Live Quant News Feed (Flask + yfinance)

A minimal Flask application that:

* Serves a simple home endpoint.
* Provides a `/price` endpoint for the latest market price of a ticker.
* Streams live NSE news headlines via **Server‑Sent Events** (`/news-sse`).

The front‑end (in the GitHub‑Pages CV) can embed the JavaScript snippet from the optimizer section to show a live news feed with near‑zero latency.

## Running locally
```bash
python -m venv .venv
. .venv/Scripts/activate   # on Windows PowerShell
pip install -r requirements.txt
python app.py
```
Visit `http://localhost:3000` and open the Optimizer section.

## Deploying to Vercel
1. Install the Vercel CLI (`npm i -g vercel`).
2. Run `vercel` inside the project folder.
3. Follow the prompts – Vercel will detect the Flask app, install dependencies, and expose the endpoints.

## Repository layout
```
my-python-app/
├─ app.py            # Flask server with SSE news endpoint
├─ requirements.txt  # Flask, yfinance, flask-sse
├─ .gitignore        # standard python ignores
└─ README.md
```
