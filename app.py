"""
SignalEdge — Live Crypto & Forex Signal Website
Free to host on Render.com. Data from CoinGecko + Frankfurter (no API keys needed).
"""

from flask import Flask, render_template, jsonify
import requests
from datetime import datetime, timedelta
import time

app = Flask(__name__)

# ── Cache (avoids hitting APIs on every page load) ──────────────────────────
_cache        = {}
_cache_time   = 0
CACHE_SECONDS = 300   # refresh every 5 minutes


# ── Technical Indicators ────────────────────────────────────────────────────

def calculate_rsi(closes, period=14):
    """Standard RSI from a list of closing prices."""
    if len(closes) < period + 1:
        return 50
    gains, losses = [], []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100
    rs  = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 1)


def crypto_signal(closes, current_price, change_24h):
    """
    Returns (signal, reason, confidence, color).
    Signals: STRONG BUY / BUY / NEUTRAL / SELL / STRONG SELL
    """
    if len(closes) < 7:
        return "NEUTRAL", "Not enough data yet", 45, "gray"

    rsi   = calculate_rsi(closes)
    ma7   = sum(closes[-7:]) / 7
    ma14  = sum(closes[-min(14, len(closes)):]) / min(14, len(closes))
    above_ma7  = current_price > ma7
    above_ma14 = current_price > ma14
    golden     = ma7 > ma14

    if rsi < 30 and above_ma7:
        return "STRONG BUY",  f"RSI oversold at {rsi} + price above 7-day MA",         84, "green"
    if rsi < 40 and above_ma14:
        return "BUY",         f"RSI low ({rsi}) — uptrend confirmed by MA",             69, "green"
    if rsi > 70 and not above_ma7:
        return "STRONG SELL", f"RSI overbought at {rsi} + price below 7-day MA",        81, "red"
    if rsi > 60 and not above_ma14:
        return "SELL",        f"RSI high ({rsi}) — downtrend confirmed by MA",          66, "red"
    if golden and above_ma7:
        return "BUY",         f"MA golden cross detected — RSI: {rsi}",                 62, "green"
    if not golden and not above_ma7:
        return "SELL",        f"MA bearish cross — RSI: {rsi}",                         59, "red"
    return "NEUTRAL",         f"No clear pattern — RSI: {rsi}",                         47, "gray"


def forex_signal(pct_change_7d, pair):
    """Signal for forex pairs based on 7-day momentum."""
    is_ngn = "NGN" in pair

    if is_ngn:
        if pct_change_7d > 2:
            return "SELL NGN",  f"Naira weakening — USD/NGN up {pct_change_7d:.1f}% this week",    71, "red"
        if pct_change_7d < -2:
            return "BUY NGN",   f"Naira strengthening — USD/NGN down {abs(pct_change_7d):.1f}%",   67, "green"
        return "NEUTRAL",       "USD/NGN stable this week",                                          50, "gray"

    if pct_change_7d > 1.0:
        return "BUY",   f"7-day momentum +{pct_change_7d:.1f}%",   63, "green"
    if pct_change_7d < -1.0:
        return "SELL",  f"7-day momentum {pct_change_7d:.1f}%",    61, "red"
    return "NEUTRAL",   "Range-bound this week",                    48, "gray"


# ── Data Fetching ───────────────────────────────────────────────────────────

def fetch_crypto():
    """Fetch BTC, ETH, BNB prices + 14-day history from CoinGecko (free, no key)."""
    coins = [
        ("bitcoin",      "BTC/USD"),
        ("ethereum",     "ETH/USD"),
        ("binancecoin",  "BNB/USD"),
        ("solana",       "SOL/USD"),
    ]
    results = {}

    for coin_id, label in coins:
        try:
            # Current price + 24h change
            p = requests.get(
                f"https://api.coingecko.com/api/v3/simple/price"
                f"?ids={coin_id}&vs_currencies=usd&include_24hr_change=true",
                timeout=10
            ).json()
            price      = p[coin_id]["usd"]
            change_24h = round(p[coin_id].get("usd_24h_change", 0), 2)

            # 14-day daily closes
            h = requests.get(
                f"https://api.coingecko.com/api/v3/coins/{coin_id}"
                f"/market_chart?vs_currency=usd&days=14&interval=daily",
                timeout=10
            ).json()
            closes = [row[1] for row in h.get("prices", [])]

            signal, reason, confidence, color = crypto_signal(closes, price, change_24h)

            results[label] = {
                "price":      f"${price:,.2f}",
                "change_24h": change_24h,
                "signal":     signal,
                "reason":     reason,
                "confidence": confidence,
                "color":      color,
            }
            time.sleep(0.6)   # be polite to free API

        except Exception:
            results[label] = {
                "price": "N/A", "change_24h": 0,
                "signal": "NEUTRAL", "reason": "Data unavailable",
                "confidence": 0, "color": "gray",
            }

    return results


def fetch_forex():
    """Fetch EUR/USD, GBP/USD, USD/NGN from Frankfurter API (free, no key)."""
    currencies = ["EUR", "GBP", "NGN"]
    labels     = {"EUR": "EUR/USD", "GBP": "GBP/USD", "NGN": "USD/NGN"}
    results    = {}

    try:
        # Current rates
        current = requests.get(
            "https://api.frankfurter.app/latest?from=USD",
            timeout=10
        ).json().get("rates", {})

        # 7-day history
        start = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        end   = datetime.now().strftime("%Y-%m-%d")
        hist  = requests.get(
            f"https://api.frankfurter.app/{start}..{end}?from=USD",
            timeout=10
        ).json().get("rates", {})
        dates = sorted(hist.keys())

        for cur in currencies:
            label        = labels[cur]
            current_rate = current.get(cur, 0)

            # 7-day % change
            if len(dates) >= 2:
                old_rate   = hist[dates[0]].get(cur, current_rate)
                pct_change = ((current_rate - old_rate) / old_rate * 100) if old_rate else 0
            else:
                pct_change = 0

            # Display price
            if cur == "NGN":
                display = f"₦{current_rate:,.2f}"
            elif cur in ("EUR", "GBP"):
                rate    = 1 / current_rate if current_rate else 0
                symbol  = "€" if cur == "EUR" else "£"
                display = f"{symbol}{rate:.4f}"
            else:
                display = f"{current_rate:.4f}"

            signal, reason, confidence, color = forex_signal(round(pct_change, 2), label)

            results[label] = {
                "price":      display,
                "change_7d":  round(pct_change, 2),
                "signal":     signal,
                "reason":     reason,
                "confidence": confidence,
                "color":      color,
            }

    except Exception:
        for cur in currencies:
            results[labels[cur]] = {
                "price": "N/A", "change_7d": 0,
                "signal": "NEUTRAL", "reason": "Data unavailable",
                "confidence": 0, "color": "gray",
            }

    return results


# ── Cache Layer ─────────────────────────────────────────────────────────────

def get_signals():
    global _cache, _cache_time
    if time.time() - _cache_time < CACHE_SECONDS and _cache:
        return _cache.get("crypto", {}), _cache.get("forex", {})
    crypto = fetch_crypto()
    forex  = fetch_forex()
    _cache      = {"crypto": crypto, "forex": forex}
    _cache_time = time.time()
    return crypto, forex


# ── Flask Routes ─────────────────────────────────────────────────────────────

@app.route("/")
def index():
    crypto, forex = get_signals()
    updated = datetime.now().strftime("%d %b %Y  %H:%M UTC")
    return render_template("index.html", crypto=crypto, forex=forex, updated=updated)


@app.route("/api/signals")
def api_signals():
    crypto, forex = get_signals()
    return jsonify({"crypto": crypto, "forex": forex})


if __name__ == "__main__":
    app.run(debug=False, host="0.0.0.0", port=5000)
