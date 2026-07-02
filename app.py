"""
SignalEdge — Live Crypto & Forex Signal Website
Free to host on Render.com. Data from CoinGecko + Frankfurter (no API keys needed).
"""

from flask import Flask, render_template, jsonify
import json
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
    """Fetch BTC, ETH, BNB, SOL via Yahoo Finance (free, no key, US-accessible)."""
    symbols = ["BTC-USD", "ETH-USD", "BNB-USD", "SOL-USD"]
    labels  = {"BTC-USD": "BTC/USD", "ETH-USD": "ETH/USD", "BNB-USD": "BNB/USD", "SOL-USD": "SOL/USD"}
    results = {}
    headers = {"User-Agent": "Mozilla/5.0"}

    for sym in symbols:
        label = labels[sym]
        try:
            r = requests.get(
                f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval=1d&range=16d",
                headers=headers,
                timeout=15,
            ).json()
            result = r.get("chart", {}).get("result", [None])[0]
            if not result:
                raise ValueError("no result")

            meta       = result.get("meta", {})
            price      = float(meta.get("regularMarketPrice", 0))
            prev       = float(meta.get("chartPreviousClose", price) or price)
            change_24h = round((price - prev) / prev * 100, 2) if prev else 0

            raw_closes = result.get("indicators", {}).get("quote", [{}])[0].get("close", [])
            closes     = [float(c) for c in raw_closes if c is not None]

            signal, reason, confidence, color = crypto_signal(closes, price, change_24h)

            results[label] = {
                "price":      f"${price:,.2f}",
                "change_24h": change_24h,
                "signal":     signal,
                "reason":     reason,
                "confidence": confidence,
                "color":      color,
            }
            time.sleep(0.3)

        except Exception:
            results[label] = {
                "price": "N/A", "change_24h": 0,
                "signal": "NEUTRAL", "reason": "Data unavailable",
                "confidence": 0, "color": "gray",
            }

    return results


def fetch_forex():
    """
    EUR/USD, GBP/USD — Frankfurter API (ECB data, free, no key).
    USD/NGN          — fawazahmed0 currency API (free, no key, includes NGN + history).
    """
    results = {}

    # ── EUR / GBP via Frankfurter ────────────────────────────────────────────
    try:
        current = requests.get(
            "https://api.frankfurter.app/latest?from=USD",
            timeout=10
        ).json().get("rates", {})

        start = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        end   = datetime.now().strftime("%Y-%m-%d")
        hist  = requests.get(
            f"https://api.frankfurter.app/{start}..{end}?from=USD",
            timeout=10
        ).json().get("rates", {})
        dates = sorted(hist.keys())

        for cur, label in [("EUR", "EUR/USD"), ("GBP", "GBP/USD")]:
            current_rate = current.get(cur, 0)
            if len(dates) >= 2:
                old_rate   = hist[dates[0]].get(cur, current_rate)
                pct_change = ((current_rate - old_rate) / old_rate * 100) if old_rate else 0
            else:
                pct_change = 0
            rate    = 1 / current_rate if current_rate else 0
            symbol  = "€" if cur == "EUR" else "£"
            display = f"{symbol}{rate:.4f}"
            signal, reason, confidence, color = forex_signal(round(pct_change, 2), label)
            results[label] = {
                "price": display, "change_7d": round(pct_change, 2),
                "signal": signal, "reason": reason,
                "confidence": confidence, "color": color,
            }

    except Exception:
        for label in ("EUR/USD", "GBP/USD"):
            results[label] = {
                "price": "N/A", "change_7d": 0,
                "signal": "NEUTRAL", "reason": "Data unavailable",
                "confidence": 0, "color": "gray",
            }

    # ── USD/NGN via fawazahmed0 (free CDN-hosted currency API) ───────────────
    try:
        cur_r   = requests.get(
            "https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@latest/v1/currencies/usd.json",
            timeout=10
        ).json()
        ngn_now = cur_r["usd"].get("ngn", 0)

        d7      = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        old_r   = requests.get(
            f"https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@{d7}/v1/currencies/usd.json",
            timeout=10
        ).json()
        ngn_old = old_r["usd"].get("ngn", ngn_now)

        ngn_pct = round(((ngn_now - ngn_old) / ngn_old * 100) if ngn_old else 0, 2)
        signal, reason, confidence, color = forex_signal(ngn_pct, "USD/NGN")
        results["USD/NGN"] = {
            "price": f"₦{ngn_now:,.2f}", "change_7d": ngn_pct,
            "signal": signal, "reason": reason,
            "confidence": confidence, "color": color,
        }

    except Exception:
        results["USD/NGN"] = {
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

    btc        = crypto.get("BTC/USD", {})
    btc_signal = btc.get("signal", "NEUTRAL")
    btc_reason = btc.get("reason", "indicators are mixed")
    btc_price  = btc.get("price", "N/A")
    btc_change = btc.get("change_24h", 0)
    direction  = ("upward" if btc_signal in ("BUY", "STRONG BUY")
                  else "downward" if btc_signal in ("SELL", "STRONG SELL")
                  else "sideways")
    chg_str    = (f"up {abs(btc_change):.2f}%" if btc_change > 0
                  else f"down {abs(btc_change):.2f}%" if btc_change < 0
                  else "flat")
    market_summary_text = (
        f"Daily Briefing: Bitcoin ({btc_price}) is showing a {btc_signal} signal "
        f"— {btc_reason}. BTC has moved {chg_str} over the past 24 hours, reflecting "
        f"{direction} momentum. See the individual asset signals below, or visit the "
        f"Education section to learn how RSI and Moving Averages drive each call."
    )

    return render_template(
        "index.html",
        crypto=crypto, forex=forex, updated=updated,
        market_summary_text=market_summary_text
    )


@app.route("/ads.txt")
def ads_txt():
    return "google.com, pub-7621852470505552, DIRECT, f08c47fec0942fa0\n", 200, {"Content-Type": "text/plain"}


@app.route("/privacy")
def privacy():
    return render_template("privacy.html")


@app.route("/terms")
def terms():
    return render_template("terms.html")


@app.route("/glossary")
def glossary():
    return render_template("glossary.html")


@app.route("/about")
def about():
    return render_template("about.html")


@app.route("/contact")
def contact():
    return render_template("contact.html")


@app.route("/education")
def education():
    with open("articles.json", encoding="utf-8") as f:
        articles = json.load(f)
    return render_template("education.html", articles=articles)


@app.route("/api/signals")
def api_signals():
    crypto, forex = get_signals()
    return jsonify({"crypto": crypto, "forex": forex})


if __name__ == "__main__":
    app.run(debug=False, host="0.0.0.0", port=5000)
