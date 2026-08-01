#!/usr/bin/env python3
"""
📰 ULTIMATE RSS BOT – FAST & SMART
✅ पोलिंग इंटरव्हल ६० सेकंद (किंवा कमी)
✅ डायनॅमिक इंटरव्हल – बातम्या आल्यास ३० सेकंद
✅ प्रायोरिटी कीवर्डस (buyback, results, dividend)
✅ अचूक सेंटिमेंट (VADER + extra weighting)
✅ प्रत्येक स्टॉकसाठी एकच अलर्ट
✅ Telegram, REST API, Price Impact, Daily Report
✅ Web Dashboard – with clickable news titles
"""

import asyncio
import aiohttp
import feedparser
import re
import logging
import sqlite3
import requests
import threading
import warnings
import math
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Optional, Tuple
import yfinance as yf
from flask import Flask, jsonify, request
import pytz

# ==================== Config ====================
TELEGRAM_BOT_TOKEN = '8634800722:AAESXRx8Xx3i1mqQvJCsh8ecLd0eP3kPdJQ'
TELEGRAM_CHAT_ID = '1106122116'
CHECK_INTERVAL = 60
MAX_ITEMS_PER_FEED = 10
MIN_SENTIMENT_SCORE = 1
NEWS_AGE_LIMIT = 86400
DB_FILE = 'news_storage.db'
WATCHLIST = ['RELIANCE', 'HDFCBANK', 'ICICIBANK', 'INFY', 'TATAMOTORS', 'SBIN', 'BAJFINANCE', 'TRENT', 'DIXON', 'HAL']
API_PORT = 5000

# ==================== Priority Keywords ====================
HIGH_IMPACT_KEYWORDS = [
    "buyback", "dividend", "bonus", "stock split", "results", "quarterly",
    "approval", "contract", "partnership", "acquisition", "merger", "expansion",
    "order", "win", "launch", "breakthrough", "patent", "FDA approval"
]
NEGATIVE_KEYWORDS = [
    "fraud", "default", "investigation", "scam", "penalty", "lawsuit",
    "downgrade", "selloff", "crash", "plunge", "loss", "misses"
]

# ==================== STOCKS_MAP (full) ====================
STOCKS_MAP = {
    "RELIANCE": "RELIANCE.NS", "HDFC BANK": "HDFCBANK.NS", "HDFCBANK": "HDFCBANK.NS",
    "ICICI BANK": "ICICIBANK.NS", "ICICIBANK": "ICICIBANK.NS",
    "INFOSYS": "INFY.NS", "INFY": "INFY.NS",
    "TATA MOTORS": "TATAMOTORS.NS", "TATAMOTORS": "TATAMOTORS.NS",
    "SBIN": "SBIN.NS", "SBI": "SBIN.NS",
    "BAJAJ FINANCE": "BAJFINANCE.NS", "BAJFINANCE": "BAJFINANCE.NS",
    "TRENT": "TRENT.NS", "DIXON": "DIXON.NS", "HAL": "HAL.NS",
    "NTPC": "NTPC.NS", "POWER GRID": "POWERGRID.NS", "ONGC": "ONGC.NS",
    "COAL INDIA": "COALINDIA.NS", "TATA STEEL": "TATASTEEL.NS",
    "HINDALCO": "HINDALCO.NS", "JSW STEEL": "JSWSTEEL.NS", "VEDANTA": "VEDL.NS",
    "BHARTI AIRTEL": "BHARTIARTL.NS", "ITC": "ITC.NS", "TITAN": "TITAN.NS",
    "ASIAN PAINTS": "ASIANPAINT.NS", "ULTRATECH": "ULTRACEMCO.NS",
    "ZOMATO": "ZOMATO.NS", "PAYTM": "PAYTM.NS",
    "SUN PHARMA": "SUNPHARMA.NS", "CIPLA": "CIPLA.NS", "DR REDDY": "DRREDDY.NS",
    "LUPIN": "LUPIN.NS", "APOLLO HOSPITALS": "APOLLOHOSP.NS",
    "DLF": "DLF.NS", "INDIGO": "INDIGO.NS", "BSE": "BSE.NS",
    "M&M": "M&M.NS", "HEROMOTOCO": "HEROMOTOCO.NS",
    "TECHM": "TECHM.NS", "WIPRO": "WIPRO.NS", "HCLTECH": "HCLTECH.NS",
    "LT": "LT.NS", "AXIS BANK": "AXISBANK.NS", "KOTAK BANK": "KOTAKBANK.NS",
    "MARUTI": "MARUTI.NS", "SUN TV": "SUNTV.NS", "PIDILITE": "PIDILITIND.NS",
    "DABUR": "DABUR.NS", "BRITANNIA": "BRITANNIA.NS", "NESTLE": "NESTLEIND.NS",
    "HINDUNILVR": "HINDUNILVR.NS", "BAJAJ AUTO": "BAJAJ-AUTO.NS",
    "ADANI PORTS": "ADANIPORTS.NS", "ADANI ENTERPRISES": "ADANIENT.NS"
}

MACRO_KEYWORDS = [
    "rbi", "fed", "crude", "oil", "dollar", "inr", "inflation", "cpi",
    "ppi", "gdp", "unemployment", "rate cut", "rate hike", "recession",
    "stimulus", "treasury", "yield", "bond", "forex", "rupee", "fii", "dii",
    "banking", "monetary policy", "budget", "trade deficit", "nifty", "sensex"
]

SECTOR_MAP = {
    "IT": ["INFY.NS", "TECHM.NS", "WIPRO.NS", "HCLTECH.NS", "LT.NS"],
    "Banking": ["HDFCBANK.NS", "ICICIBANK.NS", "SBIN.NS", "AXISBANK.NS", "KOTAKBANK.NS"],
    "Auto": ["TATAMOTORS.NS", "M&M.NS", "HEROMOTOCO.NS", "MARUTI.NS"],
    "FMCG": ["ITC.NS", "ASIANPAINT.NS", "HINDUNILVR.NS", "NESTLE.NS", "BRITANNIA.NS"],
    "Pharma": ["SUNPHARMA.NS", "CIPLA.NS", "DRREDDY.NS", "LUPIN.NS"],
    "Metals": ["TATASTEEL.NS", "HINDALCO.NS", "JSWSTEEL.NS", "VEDL.NS"],
    "Energy": ["RELIANCE.NS", "ONGC.NS", "COALINDIA.NS", "POWERGRID.NS"],
    "Finance": ["BAJFINANCE.NS", "SBIN.NS"],
    "Retail": ["TRENT.NS"],
    "Others": ["DIXON.NS", "HAL.NS", "NTPC.NS", "DLF.NS", "INDIGO.NS", "BSE.NS", "ADANIPORTS.NS"]
}

# ==================== Logging ====================
warnings.filterwarnings("ignore")
logging.getLogger('urllib3').setLevel(logging.ERROR)
logging.getLogger('aiohttp').setLevel(logging.ERROR)
logging.getLogger('requests').setLevel(logging.ERROR)
logging.getLogger('yfinance').setLevel(logging.ERROR)
logging.getLogger('feedparser').setLevel(logging.ERROR)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# ==================== Database ====================
def get_db_connection():
    return sqlite3.connect(DB_FILE, check_same_thread=False)

def init_db():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS news (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT, symbol TEXT, display_name TEXT, title TEXT,
            link TEXT, sentiment TEXT, score INTEGER, type TEXT, is_read INTEGER DEFAULT 0,
            source TEXT,
            UNIQUE(title, link)
        )''')
    c.execute("PRAGMA table_info(news)")
    columns = [col[1] for col in c.fetchall()]
    if 'source' not in columns:
        c.execute("ALTER TABLE news ADD COLUMN source TEXT")
    
    c.execute('''CREATE TABLE IF NOT EXISTS price_impact (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT, event_time TEXT, price_at_event REAL,
            price_5m REAL, price_15m REAL, price_30m REAL
        )''')
    c.execute("PRAGMA table_info(price_impact)")
    columns = [col[1] for col in c.fetchall()]
    for col in ['price_5m', 'price_15m', 'price_30m']:
        if col not in columns:
            c.execute(f"ALTER TABLE price_impact ADD COLUMN {col} REAL")
    
    c.execute('''CREATE TABLE IF NOT EXISTS alert_prices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT,
            alert_time TEXT,
            price REAL,
            UNIQUE(symbol, alert_time)
        )''')
    c.execute('''CREATE TABLE IF NOT EXISTS daily_report_flag (
            date TEXT PRIMARY KEY,
            sent INTEGER DEFAULT 0
        )''')
    conn.commit()
    conn.close()

def save_alert_price(symbol: str, price: float):
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("INSERT OR IGNORE INTO alert_prices (symbol, alert_time, price) VALUES (?, ?, ?)",
                  (symbol, datetime.now().isoformat(), price))
        conn.commit()
        conn.close()
    except:
        pass

def news_exists(title, link) -> bool:
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT 1 FROM news WHERE title=? OR link=?", (title, link))
        exists = c.fetchone() is not None
        conn.close()
        return exists
    except:
        return False

def insert_news(item: Dict):
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute('''INSERT OR IGNORE INTO news 
            (timestamp, symbol, display_name, title, link, sentiment, score, type, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''', (
            datetime.now().isoformat(),
            item.get('symbol', ''), item.get('display_name', ''),
            item.get('title', ''), item.get('link', ''),
            item.get('sentiment', ''), item.get('score', 0), item.get('type', ''),
            item.get('source', 'RSS')
        ))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"DB insert error: {e}")

def get_news_count() -> int:
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM news")
        count = c.fetchone()[0]
        conn.close()
        return count
    except:
        return 0

# ==================== Summarization ====================
try:
    from sumy.parsers.plaintext import PlaintextParser
    from sumy.nlp.tokenizers import Tokenizer
    from sumy.summarizers.text_rank import TextRankSummarizer
    SUMMY_AVAILABLE = True
except:
    SUMMY_AVAILABLE = False

def summarize_text(text: str, max_sentences: int = 2) -> str:
    if not text or len(text.split()) < 15:
        return text[:80] + "..."
    if SUMMY_AVAILABLE:
        try:
            parser = PlaintextParser.from_string(text, Tokenizer("english"))
            summarizer = TextRankSummarizer()
            summary = summarizer(parser.document, max_sentences)
            if summary:
                return " ".join(str(s) for s in summary)
        except:
            pass
    try:
        from collections import Counter
        sentences = re.split(r'(?<=[.!?])\s+', text)
        if len(sentences) <= 2:
            return text[:100] + "..."
        words = re.findall(r'\w+', text.lower())
        word_freq = Counter(words)
        stopwords = {'the','a','an','of','for','on','at','to','in','and','or','with','from','by'}
        for sw in stopwords:
            if sw in word_freq:
                del word_freq[sw]
        if not word_freq:
            return text[:100] + "..."
        sent_scores = {}
        for sent in sentences:
            sent_words = re.findall(r'\w+', sent.lower())
            if not sent_words:
                continue
            score = sum(word_freq.get(w, 0) for w in sent_words) / len(sent_words)
            sent_scores[sent] = score
        sorted_sents = sorted(sent_scores.items(), key=lambda x: x[1], reverse=True)
        if not sorted_sents:
            return text[:100] + "..."
        best_sents = [s[0] for s in sorted_sents[:max_sentences]]
        return " ".join(best_sents)
    except:
        return text[:100] + "..."

# ==================== Advanced Sentiment ====================
try:
    from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
    VADER_AVAILABLE = True
    vader_analyzer = SentimentIntensityAnalyzer()
except:
    VADER_AVAILABLE = False

def analyze_sentiment(title: str) -> Tuple[str, int]:
    if not title:
        return "⚪ NEUTRAL", 0
    score = 0
    if VADER_AVAILABLE:
        try:
            scores = vader_analyzer.polarity_scores(title)
            score = int(scores['compound'] * 10)
        except:
            pass
    title_lower = title.lower()
    for kw in HIGH_IMPACT_KEYWORDS:
        if kw in title_lower:
            score += 3
    for kw in NEGATIVE_KEYWORDS:
        if kw in title_lower:
            score -= 3
    score = max(-10, min(10, score))
    if score >= MIN_SENTIMENT_SCORE:
        return "🟢 POSITIVE", score
    elif score <= -MIN_SENTIMENT_SCORE:
        return "🔴 NEGATIVE", score
    else:
        return "⚪ NEUTRAL", score

def extract_single_stock_symbol(title: str) -> Tuple[Optional[str], Optional[str]]:
    if not title:
        return None, None
    found = []
    for name, symbol in STOCKS_MAP.items():
        pattern = r'(?<![A-Za-z])' + re.escape(name) + r'(?![A-Za-z])'
        if re.search(pattern, title, re.IGNORECASE):
            found.append((name, symbol))
    if len(found) == 1:
        return found[0][1], found[0][0]
    elif len(found) > 1:
        for name, symbol in found:
            if name in WATCHLIST:
                return symbol, name
        return found[0][1], found[0][0]
    return None, None

def is_macro_news(title: str) -> bool:
    if not title:
        return False
    title_lower = title.lower()
    return any(kw in title_lower for kw in MACRO_KEYWORDS)

# ==================== Telegram ====================
def send_telegram_alert(message: str, disable_preview: bool = False, buttons: List[Dict] = None):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": disable_preview
    }
    if buttons:
        payload['reply_markup'] = {"inline_keyboard": [[btn] for btn in buttons]}
    try:
        resp = requests.post(url, json=payload, timeout=10)
        if resp.status_code != 200:
            logger.error(f"Telegram send error: {resp.text}")
    except Exception as e:
        logger.error(f"Telegram exception: {e}")

def is_valid_url(url: str) -> bool:
    return url and (url.startswith('http://') or url.startswith('https://'))

def get_price_for_symbol(symbol: str) -> Tuple[Optional[float], bool]:
    try:
        ticker = yf.Ticker(symbol)
        data = ticker.history(period="5d", interval="1m")
        if not data.empty:
            last_price = data['Close'].iloc[-1]
            if not math.isnan(last_price):
                return last_price, False
            else:
                daily = ticker.history(period="5d", interval="1d")
                if not daily.empty:
                    close = daily['Close'].iloc[-1]
                    if not math.isnan(close):
                        return close, True
        else:
            daily = ticker.history(period="5d", interval="1d")
            if not daily.empty:
                close = daily['Close'].iloc[-1]
                if not math.isnan(close):
                    return close, True
    except:
        pass
    return None, False

def send_aggregated_alert(symbol: str, display_name: str, items: List[Dict]):
    # Filter out neutral items (robust check)
    non_neutral = [it for it in items if 'NEUTRAL' not in it.get('sentiment', '')]
    if not non_neutral:
        return
    items = non_neutral

    sentiment = items[0].get('sentiment', '⚪ NEUTRAL')
    score = items[0].get('score', 0)
    for it in items:
        if abs(it.get('score', 0)) > abs(score):
            score = it.get('score', 0)
            sentiment = it.get('sentiment', sentiment)
    
    price, market_closed = get_price_for_symbol(symbol)
    price_line = "💰 किंमत उपलब्ध नाही"
    if price is not None:
        price_line = f"💰 बातमीच्या वेळी: ₹{price:.2f}"
        if market_closed:
            price_line += " (बाजार बंद)"
        save_alert_price(symbol, price)
    
    source = items[0].get('source', 'RSS')
    source_tag = f"📡 {source}" if source != "RSS" else ""
    priority = abs(score) >= 5
    
    headlines = []
    for idx, it in enumerate(items[:5]):
        title = it.get('title', '')
        link = it.get('link', '')
        time_str = it.get('time', '')
        summary = summarize_text(title, max_sentences=1)
        headlines.append(f"{idx+1}. {summary} ({time_str})")
    combined = "\n".join(headlines)
    if len(items) > 5:
        combined += f"\n... आणि {len(items)-5} अधिक बातम्या"
    
    msg = f"{sentiment} <b>#{display_name}</b> (Score: {score:+d})\n"
    msg += f"📌 <b>{len(items)} बातम्या</b> {source_tag}\n"
    msg += price_line + "\n"
    msg += "─────────────────────\n"
    msg += combined + "\n"
    first_link = items[0].get('link', '')
    if is_valid_url(first_link):
        msg += f"\n🔗 <a href='{first_link}'>पहिली बातमी वाचा</a>"
    if priority:
        msg = "🚨 <b>HIGH IMPACT</b> 🚨\n" + msg
    send_telegram_alert(msg, disable_preview=False)

# ==================== Price Impact ====================
def track_price_impact(symbol: str, event_time: datetime, price_at_event: float):
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute('''INSERT INTO price_impact (symbol, event_time, price_at_event)
                     VALUES (?, ?, ?)''', (symbol, event_time.isoformat(), price_at_event))
        conn.commit()
        conn.close()
    except:
        pass

def check_price_impact():
    try:
        conn = get_db_connection()
        c = conn.cursor()
        cutoff = datetime.now() - timedelta(minutes=35)
        c.execute('''SELECT id, symbol, event_time, price_at_event, price_5m, price_15m, price_30m
                     FROM price_impact WHERE event_time > ? AND price_30m IS NULL''', (cutoff.isoformat(),))
        rows = c.fetchall()
        conn.close()
        for row in rows:
            try:
                id_, symbol, event_time_str, price_at_event, p5, p15, p30 = row
                event_time = datetime.fromisoformat(event_time_str)
                elapsed = (datetime.now() - event_time).total_seconds() / 60
                ticker = yf.Ticker(symbol)
                data = ticker.history(period="1d", interval="1m")
                if data.empty:
                    continue
                updates = {}
                if elapsed >= 5 and p5 is None:
                    updates['price_5m'] = data['Close'].iloc[-1] if len(data) > 0 else price_at_event
                if elapsed >= 15 and p15 is None:
                    updates['price_15m'] = data['Close'].iloc[-1] if len(data) > 0 else price_at_event
                if elapsed >= 30 and p30 is None:
                    updates['price_30m'] = data['Close'].iloc[-1] if len(data) > 0 else price_at_event
                if updates:
                    conn2 = get_db_connection()
                    c2 = conn2.cursor()
                    set_clause = ", ".join([f"{k} = ?" for k in updates.keys()])
                    values = list(updates.values()) + [id_]
                    c2.execute(f"UPDATE price_impact SET {set_clause} WHERE id = ?", values)
                    conn2.commit()
                    conn2.close()
                    display_name = [name for name, sym in STOCKS_MAP.items() if sym == symbol]
                    display_name = display_name[0] if display_name else symbol
                    change = updates.get('price_30m', updates.get('price_15m', updates.get('price_5m'))) - price_at_event
                    if abs(change) > 0.5:
                        msg = f"📊 <b>Price Impact: #{display_name}</b>\nEvent Price: ₹{price_at_event:.2f}\n"
                        if 'price_5m' in updates:
                            msg += f"5-min: ₹{updates['price_5m']:.2f} ({updates['price_5m']-price_at_event:+.2f})\n"
                        if 'price_15m' in updates:
                            msg += f"15-min: ₹{updates['price_15m']:.2f} ({updates['price_15m']-price_at_event:+.2f})\n"
                        if 'price_30m' in updates:
                            msg += f"30-min: ₹{updates['price_30m']:.2f} ({updates['price_30m']-price_at_event:+.2f})"
                        send_telegram_alert(msg)
            except:
                pass
    except:
        pass

# ==================== Helper: Get price at specific time ====================
def get_price_at_time(symbol: str, dt: datetime) -> Optional[float]:
    try:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        start = dt - timedelta(minutes=5)
        end = dt + timedelta(minutes=5)
        ticker = yf.Ticker(symbol)
        data = ticker.history(start=start, end=end, interval="1m")
        if not data.empty:
            times = data.index
            if len(times) == 0:
                return None
            closest_idx = min(range(len(times)), key=lambda i: abs(times[i] - dt))
            return data['Close'].iloc[closest_idx]
        data = ticker.history(start=dt.date(), end=dt.date() + timedelta(days=1), interval="1d")
        if not data.empty:
            return data['Close'].iloc[-1]
        return None
    except Exception as e:
        logger.debug(f"get_price_at_time error for {symbol}: {e}")
        return None

# ==================== Daily Report (Enhanced) ====================
def generate_daily_report():
    try:
        ist = pytz.timezone('Asia/Kolkata')
        now = datetime.now(ist)
        weekday = now.weekday()
        if weekday >= 5:
            return
        if now.hour < 15 or (now.hour == 15 and now.minute < 30):
            return

        today_str = now.strftime('%Y-%m-%d')
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT sent FROM daily_report_flag WHERE date=?", (today_str,))
        row = c.fetchone()
        if row and row[0] == 1:
            conn.close()
            return

        cutoff = (now - timedelta(hours=24)).isoformat()
        c.execute('''SELECT timestamp, symbol, display_name, title, link, sentiment, score, type, source 
                     FROM news WHERE timestamp > ? ORDER BY timestamp''', (cutoff,))
        rows = c.fetchall()
        if not rows:
            conn.close()
            return

        stock_news = {}
        macro_news = []
        for row in rows:
            timestamp, symbol, display_name, title, link, sentiment, score, ntype, source = row
            if ntype == 'stock' and symbol:
                if symbol not in stock_news:
                    stock_news[symbol] = {'display': display_name, 'news': []}
                stock_news[symbol]['news'].append({
                    'timestamp': datetime.fromisoformat(timestamp),
                    'title': title,
                    'link': link,
                    'sentiment': sentiment,
                    'score': score
                })
            elif ntype == 'macro':
                macro_news.append({
                    'timestamp': datetime.fromisoformat(timestamp),
                    'title': title,
                    'link': link,
                    'sentiment': sentiment,
                    'score': score
                })

        report = "📊 <b>24 तासांचा बातमी सारांश</b>\n"
        report += f"📅 {now.strftime('%d %b %Y, %I:%M %p IST')}\n"
        report += "═══════════════════════════════════\n\n"

        try:
            nifty = yf.Ticker("^NSEI")
            nifty_data = nifty.history(period="1d")
            if not nifty_data.empty:
                nifty_close = nifty_data['Close'].iloc[-1]
                nifty_open = nifty_data['Open'].iloc[0]
                nifty_change = ((nifty_close - nifty_open) / nifty_open) * 100
                report += f"📈 NIFTY 50: {nifty_close:.2f} ({nifty_change:+.2f}%)\n"
            sensex = yf.Ticker("^BSESN")
            sensex_data = sensex.history(period="1d")
            if not sensex_data.empty:
                sensex_close = sensex_data['Close'].iloc[-1]
                sensex_open = sensex_data['Open'].iloc[0]
                sensex_change = ((sensex_close - sensex_open) / sensex_open) * 100
                report += f"📈 SENSEX: {sensex_close:.2f} ({sensex_change:+.2f}%)\n"
            report += "\n"
        except:
            pass

        for symbol, data in stock_news.items():
            display = data['display']
            news_list = data['news']
            report += f"🔹 <b>{display}</b> ({len(news_list)} बातम्या)\n"

            market_closed = (now.hour > 15 or (now.hour == 15 and now.minute >= 30))
            ticker = yf.Ticker(symbol)
            close_price = None
            close_time = None
            if market_closed:
                daily = ticker.history(period="1d", interval="1d")
                if not daily.empty:
                    close_price = daily['Close'].iloc[-1]
                    close_time = daily.index[-1]
            else:
                data_hist = ticker.history(period="5d", interval="1m")
                if not data_hist.empty:
                    close_price = data_hist['Close'].iloc[-1]
                    close_time = data_hist.index[-1]

            for news in news_list:
                news_time = news['timestamp']
                price_at_time = get_price_at_time(symbol, news_time)
                if price_at_time is None:
                    price_str = "N/A"
                    change_str = ""
                else:
                    price_str = f"₹{price_at_time:.2f}"
                    if close_price is not None and not math.isnan(close_price):
                        change = ((close_price - price_at_time) / price_at_time) * 100
                        change_str = f" ({change:+.2f}%)"
                    else:
                        change_str = ""
                time_str = news_time.astimezone(ist).strftime('%I:%M %p')
                title = news['title'][:100] + ('...' if len(news['title'])>100 else '')
                sentiment_icon = news['sentiment'].split()[0] if news['sentiment'] else '⚪'
                report += f"   🕐 {time_str} {sentiment_icon} {title}\n"
                report += f"      💰 किंमत: {price_str}{change_str}\n"

            if close_price is not None and not math.isnan(close_price):
                if hasattr(close_time, 'to_pydatetime'):
                    close_dt = close_time.to_pydatetime().replace(tzinfo=timezone.utc).astimezone(ist)
                    close_time_str = close_dt.strftime('%I:%M %p')
                else:
                    close_time_str = "बाजार बंद"
                report += f"   🔒 बंद किंमत: ₹{close_price:.2f} ({close_time_str})\n"
            report += "\n"

        if macro_news:
            report += "🌍 <b>मॅक्रो/ग्लोबल बातम्या</b>\n"
            for news in macro_news[:10]:
                time_str = news['timestamp'].astimezone(ist).strftime('%I:%M %p')
                title = news['title'][:80] + ('...' if len(news['title'])>80 else '')
                sentiment_icon = news['sentiment'].split()[0] if news['sentiment'] else '⚪'
                report += f"   {time_str} {sentiment_icon} {title}\n"
            if len(macro_news) > 10:
                report += f"   ... आणि {len(macro_news)-10} अधिक\n"
            report += "\n"

        all_scores = []
        for symbol, data in stock_news.items():
            for news in data['news']:
                all_scores.append(news['score'])
        for news in macro_news:
            all_scores.append(news['score'])
        if all_scores:
            avg = sum(all_scores) / len(all_scores)
            if avg >= 2:
                mood = "🟢 तेजी (Bullish) 🐂"
            elif avg <= -2:
                mood = "🔴 मंदी (Bearish) 🐻"
            else:
                mood = "⚪ तटस्थ (Neutral) ➡️"
            report += f"📊 <b>एकूण बाजार मूड:</b> {mood} (सरासरी स्कोअर: {avg:.2f})\n"

        if len(report) > 4096:
            for i in range(0, len(report), 4000):
                send_telegram_alert(report[i:i+4000], disable_preview=False)
        else:
            send_telegram_alert(report, disable_preview=False)

        c.execute("INSERT OR REPLACE INTO daily_report_flag (date, sent) VALUES (?, ?)", (today_str, 1))
        conn.commit()
        conn.close()
        logger.info("✅ 24-तास बातमी सारांश पाठवला.")
    except Exception as e:
        logger.error(f"Daily report error: {e}")

# ==================== RSS Feeds ====================
RSS_FEEDS = [
    "https://economictimes.indiatimes.com/markets/stocks/rssfeeds/2146842.cms",
    "https://www.livemint.com/rss/markets",
    "https://www.moneycontrol.com/rss/market/stocks.xml",
    "https://www.businesstoday.in/rss/feed/markets/stocks",
    "https://www.financialexpress.com/feed/",
    "https://www.thehindubusinessline.com/markets/?service=rss",
    "https://www.zeebiz.com/rss/feeds/market.xml",
    "https://www.business-standard.com/rss/markets-106.rss",
    "https://www.cnbctv18.com/commonfeeds/v1/cne/rss/market.xml",
    "https://www.bloombergquint.com/feeds/india-markets-news.xml",
    "https://feeds.bloomberg.com/markets/news.rss",
    "https://finance.yahoo.com/news/rss/",
    "https://www.reuters.com/markets/rss",
    "https://www.cnbc.com/id/100003114/device/rss/rss.html",
    "https://www.marketwatch.com/rss/marketwatch-homepage/",
    "https://seekingalpha.com/market_currents.xml",
    "https://www.investing.com/rss/news.rss",
    "https://www.zerohedge.com/feed/aggregator",
    "https://news.google.com/rss/search?q=stock+market+NIFTY&hl=en-IN&gl=IN&ceid=IN:en",
    "https://news.google.com/rss/search?q=Indian+stock+market&hl=en-IN&gl=IN&ceid=IN:en",
]

async def fetch_rss_feed(session, url):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'application/rss+xml, application/xml, text/xml; q=0.9, */*; q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
    }
    try:
        async with session.get(url, headers=headers, timeout=15) as resp:
            if resp.status == 200:
                text = await resp.text()
                feed = feedparser.parse(text)
                items = []
                for entry in feed.entries[:MAX_ITEMS_PER_FEED]:
                    title = entry.get('title', '').strip()
                    link = entry.get('link', '')
                    if not title:
                        continue
                    pub_dt = None
                    if hasattr(entry, 'published_parsed') and entry.published_parsed:
                        pub_dt = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
                    elif hasattr(entry, 'updated_parsed') and entry.updated_parsed:
                        pub_dt = datetime(*entry.updated_parsed[:6], tzinfo=timezone.utc)
                    if not pub_dt:
                        pub_dt = datetime.now(timezone.utc)
                    age = (datetime.now(timezone.utc) - pub_dt).total_seconds()
                    if age > NEWS_AGE_LIMIT:
                        continue
                    sentiment, score = analyze_sentiment(title)
                    symbol, display = extract_single_stock_symbol(title)
                    if symbol:
                        items.append({
                            'title': title,
                            'link': link,
                            'sentiment': sentiment,
                            'score': score,
                            'symbol': symbol,
                            'display_name': display,
                            'time': pub_dt.strftime('%I:%M %p'),
                            'type': 'stock',
                            'source': 'RSS'
                        })
                    elif is_macro_news(title):
                        items.append({
                            'title': title,
                            'link': link,
                            'sentiment': sentiment,
                            'score': score,
                            'symbol': None,
                            'display_name': '🌐 मॅक्रो/ग्लोबल',
                            'time': pub_dt.strftime('%I:%M %p'),
                            'type': 'macro',
                            'source': 'RSS'
                        })
                return items
    except:
        pass
    return []

# ==================== Sentiment Trend ====================
def get_sentiment_trend(symbol: str, minutes: int = 120) -> Tuple[float, int]:
    try:
        conn = get_db_connection()
        c = conn.cursor()
        cutoff = (datetime.now() - timedelta(minutes=minutes)).isoformat()
        c.execute("SELECT score FROM news WHERE symbol=? AND timestamp > ?", (symbol, cutoff))
        rows = c.fetchall()
        conn.close()
        if not rows:
            return 0, 0
        scores = [r[0] for r in rows]
        avg = sum(scores) / len(scores)
        direction = 1 if avg > 0 else -1 if avg < 0 else 0
        return avg, direction
    except:
        return 0, 0

def get_sector_sentiment():
    sector_scores = {}
    for sector, symbols in SECTOR_MAP.items():
        scores = []
        for sym in symbols:
            avg, _ = get_sentiment_trend(sym, minutes=120)
            if avg != 0:
                scores.append(avg)
        if scores:
            sector_scores[sector] = sum(scores) / len(scores)
        else:
            sector_scores[sector] = 0
    return sector_scores

# ==================== Main Loop (Dynamic Interval) ====================
news_cache = set()
last_news_time = None
current_interval = CHECK_INTERVAL

def is_cached(title: str, link: str) -> bool:
    key = (title.lower(), link)
    return key in news_cache

def add_cache(title: str, link: str):
    key = (title.lower(), link)
    news_cache.add(key)

async def main_loop():
    global current_interval, last_news_time
    init_db()
    logger.info(f"🚀 FAST RSS बॉट सुरू (Interval: {current_interval}s) ...")

    try:
        send_telegram_alert(f"⚡ <b>FAST RSS बॉट सक्रिय</b>\n✅ इंटरव्हल: {current_interval} सेकंद\n✅ डायनॅमिक (बातम्या आल्यास ३० सेकंद)")
    except:
        pass

    while True:
        try:
            logger.info(f"🔄 RSS स्कॅन (Interval: {current_interval}s)...")
            all_items = []

            async with aiohttp.ClientSession() as session:
                tasks = [fetch_rss_feed(session, url) for url in RSS_FEEDS]
                rss_results = await asyncio.gather(*tasks)
                for items in rss_results:
                    for item in items:
                        if not is_cached(item['title'], item['link']) and not news_exists(item['title'], item['link']):
                            add_cache(item['title'], item['link'])
                            all_items.append(item)

            if all_items:
                logger.info(f"✅ {len(all_items)} नवीन बातम्या!")
                last_news_time = datetime.now()
                current_interval = 30
            else:
                logger.info("ℹ️ नवीन बातम्या नाहीत.")
                if last_news_time and (datetime.now() - last_news_time) > timedelta(minutes=5):
                    current_interval = min(120, current_interval + 10)
                else:
                    current_interval = min(120, current_interval + 5)

            if all_items:
                # ---- Insert all items into DB ----
                for it in all_items:
                    insert_news(it)

                # ---- Group items ----
                stock_dict = {}
                macro_items = []
                for item in all_items:
                    if item['type'] == 'stock':
                        sym = item['symbol']
                        if sym not in stock_dict:
                            stock_dict[sym] = []
                        stock_dict[sym].append(item)
                    else:
                        macro_items.append(item)

                # ---- Send stock alerts (let send_aggregated_alert filter neutral) ----
                for sym, items in stock_dict.items():
                    display = items[0]['display_name']
                    send_aggregated_alert(sym, display, items)   # function will filter neutral internally
                    price, _ = get_price_for_symbol(sym)
                    if price is not None:
                        track_price_impact(sym, datetime.now(), price)

                # ---- Send macro digest (filter neutral inside) ----
                if macro_items:
                    non_neutral_macro = [it for it in macro_items if 'NEUTRAL' not in it.get('sentiment', '')]
                    if non_neutral_macro:
                        msg = "🌍 <b>मॅक्रो/कॅलेंडर डायजेस्ट</b>\n─────────────────────\n"
                        for it in non_neutral_macro[:5]:
                            summary = summarize_text(it['title'], max_sentences=1)
                            msg += f"{it.get('sentiment', '⚪')} {it['display_name']}\n"
                            msg += f"🕐 {it['time']}\n📌 {summary}\n"
                            if it.get('link'):
                                msg += f"🔗 <a href='{it['link']}'>Read more</a>\n"
                            msg += "─────────────────────\n"
                        send_telegram_alert(msg, disable_preview=False)

                # ---- Overall market mood ----
                all_scores = [i.get('score', 0) for i in all_items if i.get('score', 0) != 0]
                if all_scores:
                    avg = sum(all_scores) / len(all_scores)
                    if avg >= 2:
                        mood = "🟢 तेजी (Bullish) 🐂"
                    elif avg <= -2:
                        mood = "🔴 मंदी (Bearish) 🐻"
                    else:
                        mood = "⚪ तटस्थ (Neutral) ➡️"
                    send_telegram_alert(f"📊 <b>बाजार मूड</b>\n📈 सरासरी स्कोअर: {avg:.2f}\n📊 भावना: {mood}", disable_preview=False)

                check_price_impact()

            # Daily Report
            try:
                ist = pytz.timezone('Asia/Kolkata')
                now_ist = datetime.now(ist)
                if now_ist.weekday() < 5 and (now_ist.hour > 15 or (now_ist.hour == 15 and now_ist.minute >= 30)):
                    generate_daily_report()
            except:
                pass

        except Exception as e:
            logger.error(f"🔥 Main loop error: {e}")

        await asyncio.sleep(current_interval)

# ==================== REST API & Web Dashboard ====================
app = Flask(__name__)

@app.route('/')
def home():
    return '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>📰 RSS News Dashboard</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: #f4f6f9; color: #333; padding: 20px; }
        .container { max-width: 1200px; margin: 0 auto; }
        h1 { display: flex; align-items: center; gap: 10px; color: #1a2a4a; border-bottom: 2px solid #1a2a4a; padding-bottom: 10px; }
        .status-bar { background: #fff; padding: 15px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); margin: 20px 0; display: flex; flex-wrap: wrap; gap: 20px; align-items: center; }
        .status-item { display: flex; align-items: center; gap: 5px; font-size: 14px; }
        .badge { background: #28a745; color: #fff; padding: 2px 10px; border-radius: 20px; font-size: 12px; }
        .grid { display: grid; grid-template-columns: 2fr 1fr; gap: 20px; margin-top: 20px; }
        @media (max-width: 768px) { .grid { grid-template-columns: 1fr; } }
        .card { background: #fff; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.08); padding: 20px; }
        .card h2 { font-size: 18px; margin-bottom: 15px; border-bottom: 1px solid #e9ecef; padding-bottom: 10px; }
        .news-item { padding: 10px 0; border-bottom: 1px solid #f1f3f5; font-size: 14px; }
        .news-item:last-child { border-bottom: none; }
        .news-time { color: #6c757d; font-size: 12px; margin-right: 10px; }
        .sentiment-icon { margin-right: 6px; }
        .symbol-tag { background: #e9ecef; padding: 2px 8px; border-radius: 12px; font-size: 12px; font-weight: bold; }
        .search-box { display: flex; gap: 10px; margin-bottom: 15px; }
        .search-box input { flex: 1; padding: 8px 12px; border: 1px solid #ced4da; border-radius: 4px; }
        .search-box button { padding: 8px 16px; background: #1a2a4a; color: #fff; border: none; border-radius: 4px; cursor: pointer; }
        .search-box button:hover { background: #0d1b30; }
        .sector-list { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
        .sector-item { display: flex; justify-content: space-between; padding: 6px 0; border-bottom: 1px solid #f1f3f5; font-size: 14px; }
        .trend-input { display: flex; gap: 10px; margin-bottom: 10px; }
        .trend-input input { flex: 1; padding: 8px 12px; border: 1px solid #ced4da; border-radius: 4px; }
        .trend-input button { padding: 8px 16px; background: #1a2a4a; color: #fff; border: none; border-radius: 4px; cursor: pointer; }
        .trend-result { padding: 10px; background: #f8f9fa; border-radius: 4px; }
        .refresh-btn { background: #17a2b8; color: #fff; border: none; padding: 6px 14px; border-radius: 4px; cursor: pointer; }
        .refresh-btn:hover { background: #138496; }
        .news-title-link { text-decoration: none; color: #333; }
        .news-title-link:hover { text-decoration: underline; color: #007bff; }
    </style>
</head>
<body>
<div class="container">
    <h1>📰 RSS News Dashboard</h1>
    <div class="status-bar" id="statusBar">
        <span class="status-item">🔄 Status: <span id="statusText">Loading...</span></span>
        <span class="status-item">📰 Total News: <span id="totalNews">0</span></span>
        <span class="status-item">⏱️ Interval: <span id="interval">-</span>s</span>
        <button class="refresh-btn" onclick="refreshAll()">⟳ Refresh</button>
    </div>
    <div class="grid">
        <div class="card">
            <h2>📰 Latest News (50)</h2>
            <div class="search-box">
                <input type="text" id="searchInput" placeholder="Search by keyword, symbol..." />
                <button onclick="searchNews()">Search</button>
                <button onclick="clearSearch()" style="background:#6c757d;">Clear</button>
            </div>
            <div id="newsList"></div>
        </div>
        <div>
            <div class="card" style="margin-bottom:20px;">
                <h2>📊 Sector Sentiment</h2>
                <div id="sectorList" class="sector-list"></div>
            </div>
            <div class="card">
                <h2>📈 Stock Trend</h2>
                <div class="trend-input">
                    <input type="text" id="trendSymbol" placeholder="e.g. RELIANCE.NS" />
                    <button onclick="getTrend()">Get Trend</button>
                </div>
                <div id="trendResult" class="trend-result">Enter a symbol to see sentiment trend (last 2 hours).</div>
            </div>
        </div>
    </div>
</div>
<script>
    async function fetchJSON(url) {
        const res = await fetch(url);
        if (!res.ok) throw new Error('Network error');
        return await res.json();
    }

    async function loadStatus() {
        try {
            const data = await fetchJSON('/status');
            document.getElementById('statusText').textContent = data.status || 'unknown';
            document.getElementById('totalNews').textContent = data.total_news || 0;
            document.getElementById('interval').textContent = data.interval || '-';
        } catch (e) {
            document.getElementById('statusText').textContent = '⚠️ Error';
        }
    }

    async function loadNews(query = '') {
        const url = query ? `/search?q=${encodeURIComponent(query)}` : '/news';
        try {
            const data = await fetchJSON(url);
            const list = document.getElementById('newsList');
            if (!data.length) {
                list.innerHTML = '<p style="color:#6c757d;">No news found.</p>';
                return;
            }
            list.innerHTML = data.map(n => {
                const titleText = n.title ? n.title.substring(0, 100) + (n.title.length > 100 ? '...' : '') : '';
                const titleHtml = n.link ? `<a href="${n.link}" target="_blank" class="news-title-link">${titleText}</a>` : titleText;
                return `
                <div class="news-item">
                    <span class="news-time">${n.timestamp ? new Date(n.timestamp).toLocaleString() : ''}</span>
                    <span class="sentiment-icon">${n.sentiment ? n.sentiment.split(' ')[0] : '⚪'}</span>
                    <span class="symbol-tag">${n.symbol || '📰'}</span>
                    <strong>${n.display_name || ''}</strong>
                    <span style="font-size:12px; color:#6c757d;">(score: ${n.score || 0})</span>
                    <br>
                    ${titleHtml}
                    ${n.link ? ` <a href="${n.link}" target="_blank" style="font-size:12px;">🔗</a>` : ''}
                </div>
            `}).join('');
        } catch (e) {
            document.getElementById('newsList').innerHTML = '<p style="color:red;">Error loading news.</p>';
        }
    }

    function searchNews() {
        const q = document.getElementById('searchInput').value.trim();
        if (q) loadNews(q);
        else loadNews();
    }

    function clearSearch() {
        document.getElementById('searchInput').value = '';
        loadNews();
    }

    async function loadSectors() {
        try {
            const data = await fetchJSON('/sector_sentiment');
            const container = document.getElementById('sectorList');
            container.innerHTML = Object.entries(data).map(([sector, score]) => `
                <div class="sector-item">
                    <span>${sector}</span>
                    <span style="font-weight:bold; color:${score > 1 ? '#28a745' : score < -1 ? '#dc3545' : '#6c757d'}">${score.toFixed(2)}</span>
                </div>
            `).join('');
        } catch (e) {
            document.getElementById('sectorList').innerHTML = '<p style="color:red;">Error loading sectors.</p>';
        }
    }

    async function getTrend() {
        const sym = document.getElementById('trendSymbol').value.trim();
        if (!sym) {
            document.getElementById('trendResult').textContent = 'Please enter a symbol (e.g., RELIANCE.NS)';
            return;
        }
        try {
            const data = await fetchJSON(`/trend/${encodeURIComponent(sym)}`);
            const avg = data.avg_score || 0;
            const dir = data.direction || 0;
            const dirText = dir > 0 ? '⬆️ Bullish' : dir < 0 ? '⬇️ Bearish' : '➡️ Neutral';
            document.getElementById('trendResult').innerHTML = `
                <strong>${sym}</strong><br>
                Avg Sentiment Score (2h): <span style="font-weight:bold; color:${avg > 1 ? '#28a745' : avg < -1 ? '#dc3545' : '#6c757d'}">${avg.toFixed(2)}</span><br>
                Direction: ${dirText}
            `;
        } catch (e) {
            document.getElementById('trendResult').textContent = 'Error fetching trend.';
        }
    }

    async function refreshAll() {
        await Promise.all([loadStatus(), loadNews(), loadSectors()]);
    }

    refreshAll();
    setInterval(refreshAll, 30000);
</script>
</body>
</html>
    '''

@app.route('/test', methods=['GET'])
def test():
    try:
        send_telegram_alert("🧪 <b>टेस्ट अलर्ट</b> – बॉट कार्यरत आहे.")
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/news', methods=['GET'])
def api_news():
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT * FROM news ORDER BY timestamp DESC LIMIT 50")
        rows = c.fetchall()
        conn.close()
        news_list = []
        for row in rows:
            news_list.append({
                'id': row[0],
                'timestamp': row[1],
                'symbol': row[2],
                'display_name': row[3],
                'title': row[4],
                'link': row[5],
                'sentiment': row[6],
                'score': row[7],
                'type': row[8],
                'source': row[10] if len(row) > 10 else ''
            })
        return jsonify(news_list)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/search', methods=['GET'])
def api_search():
    keyword = request.args.get('q', '')
    if not keyword:
        return jsonify({'error': 'Missing q parameter'}), 400
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT * FROM news WHERE title LIKE ? OR symbol LIKE ? ORDER BY timestamp DESC LIMIT 20", 
                  (f'%{keyword}%', f'%{keyword}%'))
        rows = c.fetchall()
        conn.close()
        results = []
        for row in rows:
            results.append({
                'timestamp': row[1],
                'symbol': row[2],
                'title': row[4],
                'link': row[5],
                'sentiment': row[6],
                'score': row[7]
            })
        return jsonify(results)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/trend/<symbol>', methods=['GET'])
def api_trend(symbol):
    avg, direction = get_sentiment_trend(symbol)
    return jsonify({'symbol': symbol, 'avg_score': avg, 'direction': direction})

@app.route('/sector_sentiment', methods=['GET'])
def api_sector():
    sectors = get_sector_sentiment()
    return jsonify(sectors)

@app.route('/status', methods=['GET'])
def api_status():
    try:
        count = get_news_count()
        return jsonify({'total_news': count, 'status': 'running', 'interval': current_interval})
    except:
        return jsonify({'status': 'error'}), 500

def run_api():
    app.run(host='0.0.0.0', port=API_PORT, debug=False, use_reloader=False)

# ==================== START ====================
if __name__ == "__main__":
    api_thread = threading.Thread(target=run_api, daemon=True)
    api_thread.start()
    logger.info(f"🌐 API & Dashboard सुरू: http://localhost:{API_PORT}")
    asyncio.run(main_loop())
