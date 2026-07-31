#!/usr/bin/env python3
"""
📰 SUPER ULTIMATE NEWS BOT (FIXED)
✅ Asyncio + aioHTTP – वेगवान समांतर फेचिंग
✅ feedparser – RSS पार्सिंग (सुरक्षित पद्धत)
✅ requests – टेलीग्राम पाठवण्यासाठी
✅ रिट्री मेकॅनिझम – अयशस्वी फीड्स पुन्हा प्रयत्न
✅ मेमरी कॅश – डुप्लिकेट तपासणी वेगवान
✅ SQLite – कायम साठा
✅ सेंटिमेंट, LTP, मार्केट मूड, वॉचलिस्ट – सर्व जुने फीचर्स
"""

import asyncio
import aiohttp
import feedparser
import time
import re
import logging
import sqlite3
import os
import requests   # <-- हे आता import केले आहे
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional, Tuple
import yfinance as yf

# ==================== कॉन्फिगरेशन ====================
TELEGRAM_BOT_TOKEN = '8634800722:AAESXRx8Xx3i1mqQvJCsh8ecLd0eP3kPdJQ'
TELEGRAM_CHAT_ID = '1106122116'
CHECK_INTERVAL = 60          # सेकंद
MAX_ITEMS_PER_FEED = 20
NEWS_AGE_LIMIT = 3600        # १ तास
MIN_SENTIMENT_SCORE = 1
DB_FILE = 'news_storage.db'
WATCHLIST = ['RELIANCE', 'HDFCBANK', 'ICICIBANK', 'INFY', 'TATAMOTORS', 'SBIN', 'BAJFINANCE', 'TRENT', 'DIXON', 'HAL']
MAX_RETRIES = 2              # अयशस्वी फीडसाठी पुन्हा प्रयत्न
RETRY_DELAY = 2              # सेकंद
# =====================================================

# 📰 फीड्स (BloombergQuint काढली)
INDIAN_NEWS_FEEDS = [
    "https://news.google.com/rss/search?q=Indian+stock+market+NIFTY+BANK+NIFTY+RELIANCE+HDFC+INFY&hl=en-IN&gl=IN&ceid=IN:en",
    "https://economictimes.indiatimes.com/markets/stocks/rssfeeds/2146842.cms",
    "https://www.livemint.com/rss/markets",
    "https://www.cnbctv18.com/commonfeeds/v1/cne/rss/market.xml",
    "https://www.moneycontrol.com/rss/market/stocks.xml",
    "https://www.business-standard.com/rss/markets-106.rss",
    # "https://www.bloombergquint.com/feeds/india-markets-news.xml", # DNS एरर, म्हणून काढली
]

GLOBAL_NEWS_FEEDS = [
    "https://feeds.a.dj.com/rss/RSSMarketsMain.xml",
    "https://www.investing.com/rss/news.rss",
    "https://www.ft.com/markets?format=rss",
]

ALL_FEEDS = INDIAN_NEWS_FEEDS + GLOBAL_NEWS_FEEDS

# स्टॉक मॅप, कीवर्ड्स (बदल नाही)
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
    "ZOMATO": "ZOMATO.NS",
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

BULLISH_KEYWORDS = [
    "beats", "surge", "jump", "rally", "record high", "all-time high",
    "positive", "upgrade", "target raised", "strong growth", "buyback",
    "dividend", "bonus", "outperform", "bullish", "profit", "gain",
    "exceeds", "above estimates", "robust", "soar", "boom", "breakout",
    "recovery", "rebound", "upbeat", "optimistic", "best", "winner",
    "approved", "clearance", "green signal", "partnership", "acquisition"
]
BEARISH_KEYWORDS = [
    "misses", "drop", "plunge", "crash", "record low", "all-time low",
    "negative", "downgrade", "target cut", "slowdown", "default",
    "fraud", "investigation", "selloff", "bearish", "loss", "decline",
    "below estimates", "weak", "slump", "tumble", "slip", "downside",
    "warning", "concern", "risk", "volatility", "uncertainty", "penalty",
    "ban", "restriction", "downtrend", "recession fears"
]

# ==================== लॉगिंग ====================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# ==================== SQLite ====================
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS news (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            symbol TEXT,
            display_name TEXT,
            title TEXT,
            link TEXT,
            sentiment TEXT,
            score INTEGER,
            type TEXT,
            is_read INTEGER DEFAULT 0,
            UNIQUE(title, link)
        )
    ''')
    conn.commit()
    conn.close()

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
        c.execute('''
            INSERT OR IGNORE INTO news 
            (timestamp, symbol, display_name, title, link, sentiment, score, type)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            datetime.now().isoformat(),
            item.get('symbol', ''),
            item.get('display_name', ''),
            item.get('title', ''),
            item.get('link', ''),
            item.get('sentiment', ''),
            item.get('score', 0),
            item.get('type', '')
        ))
        conn.commit()
    except Exception as e:
        logger.error(f"DB insert error: {e}")
    finally:
        conn.close()

# ==================== मेमरी कॅश ====================
news_cache = set()
def is_cached(title: str, link: str) -> bool:
    key = (title.lower(), link)
    return key in news_cache
def add_cache(title: str, link: str):
    key = (title.lower(), link)
    news_cache.add(key)

# ==================== सेंटिमेंट आणि स्टॉक ====================
def analyze_sentiment(title: str) -> Tuple[str, int]:
    title_lower = title.lower()
    score = 0
    for kw in BULLISH_KEYWORDS:
        if kw in title_lower:
            score += 2
    for kw in BEARISH_KEYWORDS:
        if kw in title_lower:
            score -= 2
    if "beats" in title_lower and "miss" not in title_lower:
        score += 1
    if "surprise" in title_lower and "negative" not in title_lower:
        score += 1
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

def send_news_item(item: Dict, is_first: bool = True):
    sentiment = item['sentiment']
    display = item['display_name']
    score = item['score']
    title = item['title']
    link = item['link']
    time_str = item.get('time', '')
    symbol = item.get('symbol')

    ltp_str = ""
    if symbol:
        try:
            ticker = yf.Ticker(symbol)
            data = ticker.history(period="1d", interval="1m")
            if not data.empty:
                ltp = data['Close'].iloc[-1]
                ltp_str = f" | LTP: ₹{ltp:.2f}"
        except:
            pass

    button = {"text": "📖 Read", "url": link} if link else None
    if is_first:
        msg = f"{sentiment} <b>#{display}</b> (Score: {score:+d}){ltp_str}\n"
        msg += f"🕐 {time_str}\n📌 <a href='{link}'>{title[:120]}{'...' if len(title)>120 else ''}</a>"
        send_telegram_alert(msg, disable_preview=False, buttons=[button] if button else None)
    else:
        msg = f"📌 {sentiment} #{display} (Score: {score:+d}){ltp_str}\n🔗 <a href='{link}'>{title[:80]}{'...' if len(title)>80 else ''}</a>"
        send_telegram_alert(msg, disable_preview=False, buttons=[button] if button else None)

# ==================== RSS फीड फेच (असिंक्रोनस) ====================
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
                    # सुरक्षित वेळ मिळवा
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
                    if abs(score) < MIN_SENTIMENT_SCORE:
                        continue
                    symbol, display = extract_single_stock_symbol(title)
                    if symbol:
                        items.append({
                            'title': title, 'link': link, 'sentiment': sentiment, 'score': score,
                            'symbol': symbol, 'display_name': display,
                            'time': pub_dt.strftime('%I:%M %p'), 'type': 'stock'
                        })
                    elif is_macro_news(title):
                        items.append({
                            'title': title, 'link': link, 'sentiment': sentiment, 'score': score,
                            'symbol': None, 'display_name': '🌐 मॅक्रो/ग्लोबल',
                            'time': pub_dt.strftime('%I:%M %p'), 'type': 'macro'
                        })
                logger.info(f"✅ फीड {url} मधून {len(items)} बातम्या मिळाल्या")
                return items
            else:
                logger.warning(f"⚠️ फीड {url} वरून {resp.status} आला")
                return []
    except Exception as e:
        if retry < MAX_RETRIES:
            logger.warning(f"🔄 फीड {url} अयशस्वी, पुन्हा प्रयत्न {retry+1}/{MAX_RETRIES}: {e}")
            await asyncio.sleep(RETRY_DELAY)
            return await fetch_feed(session, url, retry+1)
        else:
            logger.error(f"❌ फीड {url} कायम अयशस्वी: {e}")
            return []

async def fetch_all_feeds():
    async with aiohttp.ClientSession() as session:
        tasks = [fetch_feed(session, url) for url in ALL_FEEDS]
        results = await asyncio.gather(*tasks)
        return results

# ==================== मुख्य लूप ====================
seen_stocks = set()
async def main_loop():
    global seen_stocks
    init_db()
    logger.info("🚀 सुपर न्यूज बॉट (असिंक्रोनस + feedparser) सुरू...")
    send_telegram_alert("🎯 <b>सुपर बॉट सक्रिय</b>\n✅ असिंक्रोनस फेचिंग\n✅ feedparser\n✅ मेमरी कॅश\n✅ रिट्री मेकॅनिझम")

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

            logger.info(f"📊 नवीन: {len(stock_news)} स्टॉक, {len(macro_news)} मॅक्रो")

            if stock_news or macro_news:
                # ग्रुपिंग
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

                # मॅक्रो
                if macro_news:
                    msg = "🌍 <b>मॅक्रो डायजेस्ट</b>\n─────────────────────\n"
                    for it in macro_news[:5]:
                        msg += f"{it['sentiment']} (Score: {it['score']:+d}) {it['display_name']}\n"
                        msg += f"🕐 {it['time']}\n🔗 <a href='{it['link']}'>{it['title'][:100]}{'...' if len(it['title'])>100 else ''}</a>\n─────────────────────\n"
                        insert_news(it)
                    send_telegram_alert(msg, disable_preview=False)

                # मार्केट मूड
                all_items = stock_news + macro_news
                if all_items:
                    avg = sum(i['score'] for i in all_items) / len(all_items)
                    if avg >= 1.5:
                        mood = "🟢 तेजी (Bullish) 🐂"
                    elif avg <= -1.5:
                        mood = "🔴 मंदी (Bearish) 🐻"
                    else:
                        mood = "⚪ तटस्थ (Neutral) ➡️"
                    send_telegram_alert(f"📊 <b>बाजार मूड</b>\n📈 सरासरी स्कोअर: {avg:.2f}\n📊 भावना: {mood}", disable_preview=False)

            else:
                logger.info("ℹ️ नवीन बातम्या नाहीत.")

        except Exception as e:
            logger.error(f"🔥 मुख्य लूप एरर: {e}")

        await asyncio.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    asyncio.run(main_loop())
