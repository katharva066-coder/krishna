#!/usr/bin/env python3
"""
📰 ULTIMATE SUPERNEWS BOT – ALL FEEDS LOG + DAILY PRICE MOVEMENT REPORT
✅ सर्व फीड्स स्कॅन होतात आणि लॉग दिसतात (० बातम्या असल्यासही)
✅ मार्केट बंद झाल्यावर (सोम-शुक्र, ३:३० PM) डेली प्राईस मूव्हमेंट रिपोर्ट
✅ स्टॉकचे अलर्ट प्राईस, हाय/लो, क्लोज, टाइमिंग सर्व माहिती
✅ सर्व जुने फीचर्स कायम (VADER, Summarization, API, Sector, इ.)
"""

import asyncio
import aiohttp
import feedparser
import time
import re
import logging
import sqlite3
import os
import requests
import threading
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Optional, Tuple
import yfinance as yf
from flask import Flask, jsonify, request

# ==================== लॉगिंग (Warnings दाबा) ====================
logging.getLogger('urllib3').setLevel(logging.ERROR)
logging.getLogger('aiohttp').setLevel(logging.ERROR)
logging.getLogger('requests').setLevel(logging.ERROR)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# ==================== CONFIGURATION ====================
TELEGRAM_BOT_TOKEN = '8634800722:AAESXRx8Xx3i1mqQvJCsh8ecLd0eP3kPdJQ'
TELEGRAM_CHAT_ID = '1106122116'
CHECK_INTERVAL = 60
MAX_ITEMS_PER_FEED = 20
NEWS_AGE_LIMIT = 3600
MIN_SENTIMENT_SCORE = 1
DB_FILE = 'news_storage.db'
WATCHLIST = ['RELIANCE', 'HDFCBANK', 'ICICIBANK', 'INFY', 'TATAMOTORS', 'SBIN', 'BAJFINANCE', 'TRENT', 'DIXON', 'HAL']
MAX_RETRIES = 2
RETRY_DELAY = 2
API_PORT = 5000
# =====================================================

# ==================== सेक्टर मॅप ====================
SECTOR_MAP = {
    "IT": ["INFY.NS", "TECHM.NS", "WIPRO.NS", "HCLTECH.NS", "LT.NS"],
    "Banking": ["HDFCBANK.NS", "ICICIBANK.NS", "SBIN.NS"],
    "Auto": ["TATAMOTORS.NS", "M&M.NS", "HEROMOTOCO.NS"],
    "FMCG": ["ITC.NS", "ASIANPAINT.NS"],
    "Pharma": ["SUNPHARMA.NS", "CIPLA.NS", "DRREDDY.NS", "LUPIN.NS"],
    "Metals": ["TATASTEEL.NS", "HINDALCO.NS", "JSWSTEEL.NS", "VEDL.NS"],
    "Energy": ["RELIANCE.NS", "ONGC.NS", "COALINDIA.NS", "POWERGRID.NS"],
    "Finance": ["BAJFINANCE.NS", "SBIN.NS"],
    "Retail": ["TRENT.NS"],
    "Others": ["DIXON.NS", "HAL.NS", "NTPC.NS", "DLF.NS", "INDIGO.NS", "BSE.NS"]
}

# ==================== विस्तारित फीड्स (१४+ कार्यरत) ====================
INDIAN_NEWS_FEEDS = [
    "https://news.google.com/rss/search?q=site:moneycontrol.com+stock+market&hl=en-IN&gl=IN&ceid=IN:en",
    "https://news.google.com/rss/search?q=Indian+stock+market+NIFTY+BANK+NIFTY+RELIANCE+HDFC+INFY&hl=en-IN&gl=IN&ceid=IN:en",
    "https://economictimes.indiatimes.com/markets/stocks/rssfeeds/2146842.cms",
    "https://www.livemint.com/rss/markets",
    "https://www.cnbctv18.com/commonfeeds/v1/cne/rss/market.xml",
    "https://www.zeebiz.com/rss/feeds/market.xml",
    "https://www.businesstoday.in/rss/feed/markets/stocks",
    "https://www.moneycontrol.com/rss/market/stocks.xml",
    "https://www.bloombergquint.com/feeds/india-markets-news.xml",
    "https://www.financialexpress.com/feed/",
    "https://www.thehindubusinessline.com/markets/?service=rss",
    "https://www.businessinsider.com/rss",
]

GLOBAL_NEWS_FEEDS = [
    "https://feeds.a.dj.com/rss/RSSMarketsMain.xml",
    "https://www.ft.com/markets?format=rss",
    "https://www.reuters.com/markets/rss",
    "https://www.cnbc.com/id/100003114/device/rss/rss.html",
    "https://www.marketwatch.com/rss/marketwatch-homepage/",
    "https://seekingalpha.com/market_currents.xml",
]

ECONOMIC_CALENDAR_FEED = "https://www.investing.com/rss/economic_calendar.rss"

ALL_FEEDS = INDIAN_NEWS_FEEDS + GLOBAL_NEWS_FEEDS + [ECONOMIC_CALENDAR_FEED]

# ==================== STOCKS_MAP (ZOMATO चा symbol सुधारला – ET) ====================
STOCKS_MAP = {
    "RELIANCE": "RELIANCE.NS",
    "HDFC BANK": "HDFCBANK.NS", "HDFCBANK": "HDFCBANK.NS",
    "ICICI BANK": "ICICIBANK.NS", "ICICIBANK": "ICICIBANK.NS",
    "INFOSYS": "INFY.NS", "INFY": "INFY.NS",
    "TATA MOTORS": "TATAMOTORS.NS", "TATAMOTORS": "TATAMOTORS.NS",
    "SBIN": "SBIN.NS", "SBI": "SBIN.NS",
    "BAJAJ FINANCE": "BAJFINANCE.NS", "BAJFINANCE": "BAJFINANCE.NS",
    "TRENT": "TRENT.NS",
    "DIXON": "DIXON.NS",
    "HAL": "HAL.NS",
    "NTPC": "NTPC.NS",
    "POWER GRID": "POWERGRID.NS",
    "ONGC": "ONGC.NS",
    "COAL INDIA": "COALINDIA.NS",
    "TATA STEEL": "TATASTEEL.NS",
    "HINDALCO": "HINDALCO.NS",
    "JSW STEEL": "JSWSTEEL.NS",
    "VEDANTA": "VEDL.NS",
    "BHARTI AIRTEL": "BHARTIARTL.NS",
    "ITC": "ITC.NS",
    "TITAN": "TITAN.NS",
    "ASIAN PAINTS": "ASIANPAINT.NS",
    "ULTRATECH": "ULTRACEMCO.NS",
    "ZOMATO": "ZOMATO.NS",   # योग्य symbol
    "PAYTM": "PAYTM.NS",
    "SUN PHARMA": "SUNPHARMA.NS",
    "CIPLA": "CIPLA.NS",
    "DR REDDY": "DRREDDY.NS",
    "LUPIN": "LUPIN.NS",
    "APOLLO HOSPITALS": "APOLLOHOSP.NS",
    "DLF": "DLF.NS",
    "INDIGO": "INDIGO.NS",
    "BSE": "BSE.NS",
    "M&M": "M&M.NS",
    "HEROMOTOCO": "HEROMOTOCO.NS",
    "TECHM": "TECHM.NS",
    "WIPRO": "WIPRO.NS",
    "HCLTECH": "HCLTECH.NS",
    "LT": "LT.NS",
}

MACRO_KEYWORDS = [
    "rbi", "fed", "crude", "oil", "dollar", "inr", "inflation", "cpi",
    "ppi", "gdp", "unemployment", "rate cut", "rate hike", "recession",
    "stimulus", "treasury", "yield", "bond", "forex", "rupee", "fii", "dii",
    "banking", "monetary policy", "budget", "trade deficit"
]

# ==================== SQLite ====================
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    # news टेबल
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
        logger.info("✅ कॉलम 'source' news टेबलमध्ये जोडला")
    
    # price_impact टेबल
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
            logger.info(f"✅ कॉलम {col} price_impact मध्ये जोडला")
    
    # ===== नवीन: अलर्ट प्राईस ट्रॅकिंगसाठी =====
    c.execute('''CREATE TABLE IF NOT EXISTS alert_prices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT,
            alert_time TEXT,
            price REAL,
            UNIQUE(symbol, alert_time)
        )''')
    # डेली रिपोर्ट सेन्ट फ्लॅग
    c.execute('''CREATE TABLE IF NOT EXISTS daily_report_flag (
            date TEXT PRIMARY KEY,
            sent INTEGER DEFAULT 0
        )''')
    conn.commit()
    conn.close()

# ==================== अलर्ट प्राईस सेव्ह करा ====================
def save_alert_price(symbol: str, price: float):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    try:
        c.execute("INSERT OR IGNORE INTO alert_prices (symbol, alert_time, price) VALUES (?, ?, ?)",
                  (symbol, datetime.now().isoformat(), price))
        conn.commit()
    except Exception as e:
        logger.debug(f"Alert price save error: {e}")
    finally:
        conn.close()

# ==================== डेली रिपोर्ट जनरेट करा ====================
def generate_daily_report():
    """सोम-शुक्र ३:३० नंतर हा फंक्शन कॉल करा"""
    ist = pytz.timezone('Asia/Kolkata')
    now = datetime.now(ist)
    weekday = now.weekday()
    if weekday >= 5:  # शनि-रवि
        return
    if now.hour < 15 or (now.hour == 15 and now.minute < 30):
        return  # ३:३० पूर्वी

    # आजची तारीख
    today_str = now.strftime('%Y-%m-%d')
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    # आज रिपोर्ट पाठवला का?
    c.execute("SELECT sent FROM daily_report_flag WHERE date=?", (today_str,))
    row = c.fetchone()
    if row and row[0] == 1:
        conn.close()
        return  # आधीच पाठवला

    # सर्व स्टॉक्स ज्यांना आज अलर्ट आला
    c.execute("SELECT DISTINCT symbol FROM alert_prices WHERE date(alert_time) = date(?)", (today_str,))
    symbols = [row[0] for row in c.fetchall()]
    if not symbols:
        conn.close()
        return

    report = "📊 <b>दैनिक प्राईस मूव्हमेंट रिपोर्ट</b>\n"
    report += f"📅 {now.strftime('%d %b %Y')}\n"
    report += "════════════════════════════\n\n"

    for sym in symbols:
        try:
            # अलर्ट प्राईस (पहिला)
            c.execute("SELECT alert_time, price FROM alert_prices WHERE symbol=? AND date(alert_time)=date(?) ORDER BY alert_time LIMIT 1",
                      (sym, today_str))
            alert_row = c.fetchone()
            if not alert_row:
                continue
            alert_time_str = datetime.fromisoformat(alert_row[0]).strftime('%I:%M %p')
            alert_price = alert_row[1]

            # स्टॉकचा आजचा डेटा (1-min interval)
            ticker = yf.Ticker(sym)
            data = ticker.history(period="1d", interval="1m")
            if data.empty:
                # daily data वापरू
                data_daily = ticker.history(period="1d", interval="1d")
                if data_daily.empty:
                    continue
                high = data_daily['High'].iloc[0]
                low = data_daily['Low'].iloc[0]
                close = data_daily['Close'].iloc[0]
                high_time = "N/A"
                low_time = "N/A"
            else:
                high = data['High'].max()
                low = data['Low'].min()
                close = data['Close'].iloc[-1]
                high_time = data['High'].idxmax().strftime('%I:%M %p')
                low_time = data['Low'].idxmin().strftime('%I:%M %p')

            display_name = [name for name, sym_in in STOCKS_MAP.items() if sym_in == sym]
            display_name = display_name[0] if display_name else sym

            change_from_alert = ((close - alert_price) / alert_price) * 100
            range_pct = ((high - low) / low) * 100

            report += f"🔹 <b>{display_name}</b>\n"
            report += f"   🕐 अलर्ट वेळ: {alert_time_str}  |  प्राईस: ₹{alert_price:.2f}\n"
            report += f"   📈 उच्चांक: ₹{high:.2f} ( {high_time} )\n"
            report += f"   📉 नीचांक: ₹{low:.2f} ( {low_time} )\n"
            report += f"   🔒 क्लोज: ₹{close:.2f}\n"
            report += f"   📊 अलर्ट पासून बदल: {change_from_alert:+.2f}%\n"
            report += f"   📊 दिवसाची रेंज: {range_pct:.2f}%\n\n"

        except Exception as e:
            logger.debug(f"Report gen error for {sym}: {e}")

    if len(report) < 200:
        conn.close()
        return

    # रिपोर्ट पाठवा
    send_telegram_alert(report, disable_preview=False)

    # फ्लॅग सेट करा
    c.execute("INSERT OR REPLACE INTO daily_report_flag (date, sent) VALUES (?, ?)", (today_str, 1))
    conn.commit()
    conn.close()
    logger.info("✅ दैनिक रिपोर्ट पाठवली.")

# ==================== बाकी सर्व फंक्शन्स (बदल नाही) ====================
def get_news_count() -> int:
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM news")
    count = c.fetchone()[0]
    conn.close()
    return count

def news_exists(title, link) -> bool:
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT 1 FROM news WHERE title=? OR link=?", (title, link))
    exists = c.fetchone() is not None
    conn.close()
    return exists

def insert_news(item: Dict):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    try:
        c.execute('''INSERT OR IGNORE INTO news 
            (timestamp, symbol, display_name, title, link, sentiment, score, type, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''', (
            datetime.now().isoformat(),
            item.get('symbol', ''), item.get('display_name', ''),
            item.get('title', ''), item.get('link', ''),
            item.get('sentiment', ''), item.get('score', 0), item.get('type', ''),
            item.get('source', '')
        ))
        conn.commit()
    except Exception as e:
        logger.error(f"DB insert error: {e}")
    finally:
        conn.close()

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
    # Fallback
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

# ==================== VADER Sentiment ====================
try:
    from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
    VADER_AVAILABLE = True
    vader_analyzer = SentimentIntensityAnalyzer()
except:
    VADER_AVAILABLE = False

def analyze_sentiment(title: str) -> Tuple[str, int]:
    if VADER_AVAILABLE:
        scores = vader_analyzer.polarity_scores(title)
        score = int(scores['compound'] * 10)
        score = max(-10, min(10, score))
        if score >= 3:
            return "🟢 POSITIVE", score
        elif score <= -3:
            return "🔴 NEGATIVE", score
        else:
            return "⚪ NEUTRAL", score
    else:
        title_lower = title.lower()
        score = 0
        bullish = ["beats","surge","jump","rally","record high","positive","upgrade","strong","buyback","dividend","bonus","outperform","profit","gain","soar","boom","breakout"]
        bearish = ["misses","drop","plunge","crash","record low","negative","downgrade","slowdown","default","fraud","investigation","selloff","loss","decline","below estimates","weak","slump","tumble"]
        for kw in bullish:
            if kw in title_lower:
                score += 2
        for kw in bearish:
            if kw in title_lower:
                score -= 2
        score = max(-10, min(10, score))
        if score >= 3:
            return "🟢 POSITIVE", score
        elif score <= -3:
            return "🔴 NEGATIVE", score
        else:
            return "⚪ NEUTRAL", score

def extract_single_stock_symbol(title: str) -> Tuple[Optional[str], Optional[str]]:
    found = []
    for name, symbol in STOCKS_MAP.items():
        pattern = r'(?<![A-Za-z])' + re.escape(name) + r'(?![A-Za-z])'
        if re.search(pattern, title, re.IGNORECASE):
            found.append((name, symbol))
    if len(found) == 1:
        return found[0][1], found[0][0]
    return None, None

def is_macro_news(title: str) -> bool:
    title_lower = title.lower()
    return any(kw in title_lower for kw in MACRO_KEYWORDS)

# ==================== Telegram ====================
def send_telegram_alert(message: str, disable_preview: bool = False, buttons: List[Dict] = None, priority: bool = False):
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

def send_news_item(item: Dict, is_first: bool = True):
    sentiment = item['sentiment']
    if sentiment == "⚪ NEUTRAL":
        return

    display = item['display_name']
    score = item['score']
    title = item['title']
    link = item['link']
    time_str = item.get('time', '')
    symbol = item.get('symbol')
    source = item.get('source', 'News')

    summary = summarize_text(title, max_sentences=2)

    ltp_str = ""
    if symbol:
        try:
            ticker = yf.Ticker(symbol)
            data = ticker.history(period="5d", interval="1d")
            if not data.empty:
                ltp = data['Close'].iloc[-1]
                ltp_str = f" | LTP: ₹{ltp:.2f}"
                # अलर्ट प्राईस सेव्ह करा
                save_alert_price(symbol, ltp)
        except:
            pass

    button = {"text": "📖 Read", "url": link} if link else None
    priority = abs(score) >= 5

    source_tag = f"📡 {source}" if source != "News" else ""
    if is_first:
        msg = f"{sentiment} <b>#{display}</b> (Score: {score:+d}){ltp_str}\n"
        msg += f"🕐 {time_str} {source_tag}\n"
        msg += f"📌 <b>Summary:</b> {summary}\n"
        msg += f"🔗 <a href='{link}'>Read full article</a>"
        if priority:
            msg = "🚨 <b>HIGH IMPACT</b> 🚨\n" + msg
        send_telegram_alert(msg, disable_preview=False, buttons=[button] if button else None, priority=priority)
    else:
        msg = f"📌 {sentiment} #{display} (Score: {score:+d}){ltp_str}\n"
        msg += f"📝 {summary[:80]}... {source_tag}\n"
        msg += f"🔗 <a href='{link}'>Read more</a>"
        if priority:
            msg = "🚨 <b>HIGH IMPACT</b> 🚨\n" + msg
        send_telegram_alert(msg, disable_preview=False, buttons=[button] if button else None, priority=priority)

# ==================== Price Impact (शांत) ====================
def track_price_impact(symbol: str, event_time: datetime, price_at_event: float):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    try:
        c.execute('''INSERT INTO price_impact (symbol, event_time, price_at_event)
                     VALUES (?, ?, ?)''', (symbol, event_time.isoformat(), price_at_event))
        conn.commit()
    except Exception as e:
        logger.debug(f"Price tracking debug: {e}")
    finally:
        conn.close()

def check_price_impact():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    cutoff = datetime.now() - timedelta(minutes=35)
    c.execute('''SELECT id, symbol, event_time, price_at_event, price_5m, price_15m, price_30m
                 FROM price_impact WHERE event_time > ? AND price_30m IS NULL''', (cutoff.isoformat(),))
    rows = c.fetchall()
    conn.close()
    
    for row in rows:
        id_, symbol, event_time_str, price_at_event, p5, p15, p30 = row
        event_time = datetime.fromisoformat(event_time_str)
        elapsed = (datetime.now() - event_time).total_seconds() / 60
        
        try:
            ticker = yf.Ticker(symbol)
            data = ticker.history(period="1d", interval="1m")
            if data.empty:
                continue
            
            updates = {}
            if elapsed >= 5 and p5 is None:
                price_5m = data['Close'].iloc[-1] if len(data) > 0 else price_at_event
                updates['price_5m'] = price_5m
            if elapsed >= 15 and p15 is None:
                price_15m = data['Close'].iloc[-1] if len(data) > 0 else price_at_event
                updates['price_15m'] = price_15m
            if elapsed >= 30 and p30 is None:
                price_30m = data['Close'].iloc[-1] if len(data) > 0 else price_at_event
                updates['price_30m'] = price_30m
            
            if updates:
                conn = sqlite3.connect(DB_FILE)
                c2 = conn.cursor()
                set_clause = ", ".join([f"{k} = ?" for k in updates.keys()])
                values = list(updates.values()) + [id_]
                c2.execute(f"UPDATE price_impact SET {set_clause} WHERE id = ?", values)
                conn.commit()
                conn.close()
                
                display_name = [name for name, sym in STOCKS_MAP.items() if sym == symbol]
                display_name = display_name[0] if display_name else symbol
                change = updates.get('price_30m', updates.get('price_15m', updates.get('price_5m'))) - price_at_event
                if abs(change) > 0.5:
                    msg = f"📊 <b>Price Impact: #{display_name}</b>\n"
                    msg += f"Event Price: ₹{price_at_event:.2f}\n"
                    if 'price_5m' in updates:
                        msg += f"5-min Impact: ₹{updates['price_5m']:.2f} ({updates['price_5m']-price_at_event:+.2f})\n"
                    if 'price_15m' in updates:
                        msg += f"15-min Impact: ₹{updates['price_15m']:.2f} ({updates['price_15m']-price_at_event:+.2f})\n"
                    if 'price_30m' in updates:
                        msg += f"30-min Impact: ₹{updates['price_30m']:.2f} ({updates['price_30m']-price_at_event:+.2f})\n"
                    send_telegram_alert(msg)
                    logger.info(f"📊 Price impact alert sent for {symbol}")
        except Exception as e:
            logger.debug(f"Price impact check debug: {e}")

# ==================== Twitter via Nitter ====================
TWITTER_NITTER_URL = "https://nitter.net/search/rss?q=RELIANCE+OR+HDFC+OR+INFY+OR+NIFTY+OR+BANKNIFTY&f=live"
ENABLE_NITTER_TWITTER = True

async def fetch_nitter_twitter():
    if not ENABLE_NITTER_TWITTER:
        return []
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(TWITTER_NITTER_URL, timeout=10) as resp:
                if resp.status == 200:
                    text = await resp.text()
                    feed = feedparser.parse(text)
                    items = []
                    for entry in feed.entries[:10]:
                        title = entry.get('title', '').strip()
                        link = entry.get('link', '')
                        pub_dt = None
                        if hasattr(entry, 'published_parsed') and entry.published_parsed:
                            pub_dt = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
                        if not pub_dt:
                            pub_dt = datetime.now(timezone.utc)
                        age = (datetime.now(timezone.utc) - pub_dt).total_seconds()
                        if age > NEWS_AGE_LIMIT:
                            continue
                        sentiment, score = analyze_sentiment(title)
                        if abs(score) < MIN_SENTIMENT_SCORE or sentiment == "⚪ NEUTRAL":
                            continue
                        symbol, display = extract_single_stock_symbol(title)
                        if symbol:
                            items.append({
                                'title': title[:200],
                                'link': link,
                                'sentiment': sentiment,
                                'score': score,
                                'symbol': symbol,
                                'display_name': display,
                                'time': pub_dt.strftime('%I:%M %p'),
                                'type': 'stock',
                                'source': 'Twitter(Nitter)'
                            })
                    return items
                else:
                    logger.debug(f"Nitter feed returned {resp.status} (ignored)")
                    return []
    except Exception as e:
        logger.debug(f"Nitter fetch error (ignored): {e}")
        return []

# ==================== Economic Calendar ====================
async def fetch_economic_calendar():
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(ECONOMIC_CALENDAR_FEED, timeout=10) as resp:
                if resp.status == 200:
                    text = await resp.text()
                    feed = feedparser.parse(text)
                    items = []
                    for entry in feed.entries[:5]:
                        title = entry.get('title', '').strip()
                        link = entry.get('link', '')
                        pub_dt = None
                        if hasattr(entry, 'published_parsed') and entry.published_parsed:
                            pub_dt = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
                        if not pub_dt:
                            pub_dt = datetime.now(timezone.utc)
                        age = (datetime.now(timezone.utc) - pub_dt).total_seconds()
                        if age > NEWS_AGE_LIMIT * 2:
                            continue
                        items.append({
                            'title': title,
                            'link': link,
                            'time': pub_dt.strftime('%I:%M %p'),
                            'type': 'macro',
                            'display_name': '📅 इकॉनॉमिक कॅलेंडर',
                            'source': 'Economic Calendar',
                            'sentiment': '⚪',
                            'score': 0
                        })
                    return items
                else:
                    logger.debug(f"Economic calendar feed returned {resp.status} (ignored)")
                    return []
    except Exception as e:
        logger.debug(f"Economic calendar fetch error (ignored): {e}")
        return []

# ==================== RSS फीड फेच (सर्व फीड्स लॉग) ====================
async def fetch_feed(session, url, retry=0):
    try:
        async with session.get(url, timeout=15) as resp:
            if resp.status == 200:
                text = await resp.text()
                feed = feedparser.parse(text)
                items = []
                for entry in feed.entries[:MAX_ITEMS_PER_FEED]:
                    title = entry.get('title', '').strip()
                    link = entry.get('link', '')
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
                    if abs(score) < MIN_SENTIMENT_SCORE or sentiment == "⚪ NEUTRAL":
                        continue
                    symbol, display = extract_single_stock_symbol(title)
                    if symbol:
                        items.append({
                            'title': title, 'link': link, 'sentiment': sentiment, 'score': score,
                            'symbol': symbol, 'display_name': display,
                            'time': pub_dt.strftime('%I:%M %p'), 'type': 'stock',
                            'source': 'RSS'
                        })
                    elif is_macro_news(title):
                        items.append({
                            'title': title, 'link': link, 'sentiment': sentiment, 'score': score,
                            'symbol': None, 'display_name': '🌐 मॅक्रो/ग्लोबल',
                            'time': pub_dt.strftime('%I:%M %p'), 'type': 'macro',
                            'source': 'RSS'
                        })
                # ===== सर्व फीड्स लॉग करा (मग ० बातम्या असो) =====
                logger.info(f"📡 फीड {url} मधून {len(items)} बातम्या मिळाल्या")
                return items
            else:
                logger.debug(f"फीड {url} वरून {resp.status} आला (वगळले)")
                return []
    except Exception as e:
        if retry < MAX_RETRIES:
            logger.debug(f"फीड {url} अयशस्वी, पुन्हा प्रयत्न {retry+1}/{MAX_RETRIES}")
            await asyncio.sleep(RETRY_DELAY)
            return await fetch_feed(session, url, retry+1)
        else:
            logger.debug(f"फीड {url} कायम अयशस्वी: {e}")
            return []

async def fetch_all_feeds():
    async with aiohttp.ClientSession() as session:
        tasks = [fetch_feed(session, url) for url in ALL_FEEDS]
        results = await asyncio.gather(*tasks)
        return results

# ==================== Sentiment Trend ====================
def get_sentiment_trend(symbol: str, minutes: int = 60) -> Tuple[float, int]:
    conn = sqlite3.connect(DB_FILE)
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

# ==================== Sector Sentiment ====================
def get_sector_sentiment():
    sector_scores = {}
    for sector, symbols in SECTOR_MAP.items():
        scores = []
        for sym in symbols:
            avg, _ = get_sentiment_trend(sym, minutes=60)
            if avg != 0:
                scores.append(avg)
        if scores:
            sector_scores[sector] = sum(scores) / len(scores)
        else:
            sector_scores[sector] = 0
    return sector_scores

# ==================== मुख्य लूप ====================
seen_stocks = set()
async def main_loop():
    global seen_stocks
    init_db()
    logger.info("🚀 अल्टिमेट सुपर न्यूज बॉट (सर्व फीड्स लॉग + डेली रिपोर्ट) सुरू...")

    if get_news_count() == 0:
        send_telegram_alert("🎯 <b>अल्टिमेट सुपर बॉट सक्रिय</b>\n✅ सर्व फीड्स स्कॅन होतील\n✅ डेली रिपोर्ट ३:३० नंतर\n✅ सारांश + VADER\n✅ API :5000")

    while True:
        try:
            logger.info("🔄 स्कॅन सुरू...")
            all_results = await fetch_all_feeds()
            stock_news = []
            macro_news = []
            for items in all_results:
                for item in items:
                    if is_cached(item['title'], item['link']) or news_exists(item['title'], item['link']):
                        continue
                    add_cache(item['title'], item['link'])
                    if item['type'] == 'stock':
                        stock_news.append(item)
                    else:
                        macro_news.append(item)

            # Twitter
            twitter_items = await fetch_nitter_twitter()
            for item in twitter_items:
                if is_cached(item['title'], item['link']) or news_exists(item['title'], item['link']):
                    continue
                add_cache(item['title'], item['link'])
                stock_news.append(item)

            # Economic Calendar
            eco_items = await fetch_economic_calendar()
            for item in eco_items:
                if is_cached(item['title'], item['link']) or news_exists(item['title'], item['link']):
                    continue
                add_cache(item['title'], item['link'])
                macro_news.append(item)

            if stock_news or macro_news:
                logger.info(f"📊 नवीन: {len(stock_news)} स्टॉक, {len(macro_news)} मॅक्रो")

                # Price Impact Track
                for item in stock_news:
                    if item.get('symbol'):
                        try:
                            ticker = yf.Ticker(item['symbol'])
                            data = ticker.history(period="5d", interval="1d")
                            if not data.empty:
                                price = data['Close'].iloc[-1]
                                track_price_impact(item['symbol'], datetime.now(), price)
                        except:
                            pass

                groups = {}
                for item in stock_news:
                    sym = item['symbol']
                    groups.setdefault(sym, []).append(item)
                for sym, items in groups.items():
                    is_watch = sym.split('.')[0] in WATCHLIST
                    items_sorted = sorted(items, key=lambda x: x.get('time', ''))
                    if sym not in seen_stocks or is_watch:
                        send_news_item(items_sorted[0], is_first=True)
                        seen_stocks.add(sym)
                        for it in items_sorted[1:]:
                            send_news_item(it, is_first=False)
                            await asyncio.sleep(0.2)
                    else:
                        for it in items_sorted:
                            send_news_item(it, is_first=False)
                            await asyncio.sleep(0.2)
                    for it in items_sorted:
                        insert_news(it)

                if macro_news:
                    msg = "🌍 <b>मॅक्रो/कॅलेंडर डायजेस्ट</b>\n─────────────────────\n"
                    for it in macro_news[:5]:
                        summary = summarize_text(it['title'], max_sentences=1)
                        msg += f"{it.get('sentiment', '⚪')} {it['display_name']}\n"
                        msg += f"🕐 {it['time']}\n📌 {summary}\n"
                        if it.get('link'):
                            msg += f"🔗 <a href='{it['link']}'>Read more</a>\n"
                        msg += "─────────────────────\n"
                        insert_news(it)
                    send_telegram_alert(msg, disable_preview=False)

                all_items = stock_news + macro_news
                if all_items:
                    scores = [i.get('score', 0) for i in all_items if i.get('score', 0) != 0]
                    if scores:
                        avg = sum(scores) / len(scores)
                        if avg >= 1.5:
                            mood = "🟢 तेजी (Bullish) 🐂"
                        elif avg <= -1.5:
                            mood = "🔴 मंदी (Bearish) 🐻"
                        else:
                            mood = "⚪ तटस्थ (Neutral) ➡️"
                        send_telegram_alert(f"📊 <b>बाजार मूड</b>\n📈 सरासरी स्कोअर: {avg:.2f}\n📊 भावना: {mood}", disable_preview=False)

            else:
                logger.info("ℹ️ नवीन बातम्या नाहीत.")

            check_price_impact()

            # ===== डेली रिपोर्ट तपासा (फक्त आठवड्याचे दिवस, ३:३० नंतर) =====
            try:
                import pytz
                ist = pytz.timezone('Asia/Kolkata')
                now_ist = datetime.now(ist)
                if now_ist.weekday() < 5 and (now_ist.hour > 15 or (now_ist.hour == 15 and now_ist.minute >= 30)):
                    generate_daily_report()
            except Exception as e:
                logger.debug(f"Daily report check error: {e}")

        except Exception as e:
            logger.error(f"🔥 मुख्य लूप एरर: {e}")

        await asyncio.sleep(CHECK_INTERVAL)

# ==================== REST API ====================
app = Flask(__name__)

@app.route('/news', methods=['GET'])
def api_news():
    conn = sqlite3.connect(DB_FILE)
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

@app.route('/search', methods=['GET'])
def api_search():
    keyword = request.args.get('q', '')
    if not keyword:
        return jsonify({'error': 'Missing q parameter'}), 400
    conn = sqlite3.connect(DB_FILE)
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
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM news")
    count = c.fetchone()[0]
    conn.close()
    return jsonify({'total_news': count, 'status': 'running'})

def run_api():
    app.run(host='0.0.0.0', port=API_PORT, debug=False, use_reloader=False)

# ==================== मेमरी कॅश ====================
news_cache = set()
def is_cached(title: str, link: str) -> bool:
    key = (title.lower(), link)
    return key in news_cache
def add_cache(title: str, link: str):
    key = (title.lower(), link)
    news_cache.add(key)

# ==================== सुरूवात ====================
if __name__ == "__main__":
    api_thread = threading.Thread(target=run_api, daemon=True)
    api_thread.start()
    logger.info(f"🌐 API सुरू: http://localhost:{API_PORT}/news")
    asyncio.run(main_loop())
