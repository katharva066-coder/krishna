#!/usr/bin/env python3
"""
📰 ULTIMATE NEWS ALERT BOT - सर्व स्मार्ट सुधारणांसह
✅ ८+ RSS फीड्स (Indian + Global)
✅ प्रगत सेंटिमेंट स्कोअरिंग (+-10)
✅ एकाच स्टॉकच्या बातम्यांचे ग्रुप डायजेस्ट
✅ वॉचलिस्टला प्राधान्य
✅ LTP (Last Traded Price) दाखवा
✅ मार्केट मूड (सरासरी स्कोअर)
✅ SQLite डेटाबेस (CSV ऐवजी)
✅ टेलीग्राम URL बटणे
"""

import time
import requests
import re
import logging
import sqlite3
import os
from datetime import datetime, timezone, timedelta
from bs4 import BeautifulSoup
from typing import List, Dict, Optional, Tuple
from email.utils import parsedate_to_datetime
import yfinance as yf   # LTP साठी

# ==================== कॉन्फिगरेशन ====================
TELEGRAM_BOT_TOKEN = '8634800722:AAESXRx8Xx3i1mqQvJCsh8ecLd0eP3kPdJQ'
TELEGRAM_CHAT_ID = '1106122116'
CHECK_INTERVAL = 60          # दर ६० सेकंदांनी स्कॅन
MAX_ITEMS_PER_FEED = 20
NEWS_AGE_LIMIT = 3600        # १ तास
MIN_SENTIMENT_SCORE = 1      # किमान स्कोअर
GROUP_WINDOW_SECONDS = 60    # एकाच स्टॉकच्या बातम्या एकत्र करण्याची वेळ
DB_FILE = 'news_storage.db'  # SQLite डेटाबेस
WATCHLIST = ['RELIANCE', 'HDFCBANK', 'ICICIBANK', 'INFY', 'TATAMOTORS', 'SBIN', 'BAJFINANCE', 'TRENT', 'DIXON', 'HAL']  # प्राधान्य स्टॉक्स
# =====================================================

# 📰 विस्तारित फीड्स (आता ८+)
INDIAN_NEWS_FEEDS = [
    "https://news.google.com/rss/search?q=Indian+stock+market+NIFTY+BANK+NIFTY+RELIANCE+HDFC+INFY&hl=en-IN&gl=IN&ceid=IN:en",
    "https://economictimes.indiatimes.com/markets/stocks/rssfeeds/2146842.cms",
    "https://www.livemint.com/rss/markets",
    "https://www.cnbctv18.com/commonfeeds/v1/cne/rss/market.xml",
    "https://www.moneycontrol.com/rss/market/stocks.xml",
    "https://www.business-standard.com/rss/markets-106.rss",
    "https://www.bloombergquint.com/feeds/india-markets-news.xml",
]

GLOBAL_NEWS_FEEDS = [
    "https://feeds.a.dj.com/rss/RSSMarketsMain.xml",   # WSJ
    "https://www.investing.com/rss/news.rss",
    "https://www.ft.com/markets?format=rss",
]

ALL_FEEDS = INDIAN_NEWS_FEEDS + GLOBAL_NEWS_FEEDS

# 📊 स्टॉक मॅप (विस्तारित)
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

# मॅक्रो कीवर्ड
MACRO_KEYWORDS = [
    "rbi", "fed", "crude", "oil", "dollar", "inr", "inflation", "cpi", 
    "ppi", "gdp", "unemployment", "rate cut", "rate hike", "recession",
    "stimulus", "treasury", "yield", "bond", "forex", "rupee", "fii", "dii",
    "banking", "monetary policy", "budget", "trade deficit", "current account"
]

# सेंटिमेंट कीवर्ड (विस्तारित)
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

# ==================== SQLite डेटाबेस ====================
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

def get_recent_news_count(symbol: str, minutes: int = 5) -> int:
    """गेल्या काही मिनिटांत या स्टॉकच्या किती बातम्या आल्या ते काढा"""
    cutoff = datetime.now() - timedelta(minutes=minutes)
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM news WHERE symbol=? AND timestamp > ?", (symbol, cutoff.isoformat()))
    count = c.fetchone()[0]
    conn.close()
    return count

# ==================== टेलिग्राम ====================
def send_telegram_alert(message: str, disable_preview: bool = False, buttons: List[Dict] = None):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": disable_preview
    }
    if buttons:
        payload['reply_markup'] = {
            "inline_keyboard": [[button] for button in buttons]
        }
    try:
        resp = requests.post(url, json=payload, timeout=10)
        if resp.status_code != 200:
            logger.error(f"टेलिग्राम एरर: {resp.text}")
    except Exception as e:
        logger.error(f"टेलिग्राम पाठवताना एरर: {e}")

def send_news_item(item: Dict, is_first: bool = True, show_ltp: bool = True):
    """एक बातमी पाठवा (किंवा डायजेस्टमधील एक आयटम)"""
    sentiment = item['sentiment']
    display = item['display_name']
    score = item['score']
    title = item['title']
    link = item['link']
    time_str = item.get('time', datetime.now().strftime('%I:%M %p'))
    symbol = item.get('symbol')

    # LTP मिळवा (जर show_ltp True असेल)
    ltp_str = ""
    if show_ltp and symbol:
        try:
            ticker = yf.Ticker(symbol)
            data = ticker.history(period="1d", interval="1m")
            if not data.empty:
                ltp = data['Close'].iloc[-1]
                ltp_str = f" | LTP: ₹{ltp:.2f}"
        except:
            pass

    # बटण (URL)
    button = {"text": "📖 Read Full Article", "url": link} if link else None

    # पहिल्या बातमीसाठी पूर्ण स्वरूप, नंतरच्या बातम्यांसाठी थोडक्यात
    if is_first:
        msg = f"{sentiment} <b>#{display}</b> (Score: {score:+d}){ltp_str}\n"
        msg += f"🕐 {time_str}\n"
        msg += f"📌 <a href='{link}'>{title[:100]}{'...' if len(title)>100 else ''}</a>"
        send_telegram_alert(msg, disable_preview=False, buttons=[button] if button else None)
    else:
        # रिपीट बातमीसाठी एक-ओळ
        msg = f"📌 {sentiment} #{display} (Score: {score:+d}){ltp_str}\n"
        msg += f"🔗 <a href='{link}'>{title[:80]}{'...' if len(title)>80 else ''}</a>"
        send_telegram_alert(msg, disable_preview=False, buttons=[button] if button else None)

# ==================== सेंटिमेंट आणि स्टॉक एक्सट्रॅक्टर ====================
def analyze_sentiment(title: str) -> Tuple[str, int]:
    title_lower = title.lower()
    score = 0
    for kw in BULLISH_KEYWORDS:
        if kw in title_lower:
            score += 2
    for kw in BEARISH_KEYWORDS:
        if kw in title_lower:
            score -= 2
    # काही फ्रेंच/स्पेशल केसेस
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
    found_stocks = []
    for name, symbol in STOCKS_MAP.items():
        pattern = r'(?<![A-Za-z])' + re.escape(name) + r'(?![A-Za-z])'
        if re.search(pattern, title, re.IGNORECASE):
            found_stocks.append((name, symbol))
    if len(found_stocks) == 1:
        return found_stocks[0][1], found_stocks[0][0]
    return None, None

def is_macro_news(title: str) -> bool:
    title_lower = title.lower()
    for kw in MACRO_KEYWORDS:
        if kw in title_lower:
            return True
    return False

# ==================== RSS फीड वाचक ====================
def fetch_feed(url: str) -> List[Dict]:
    items = []
    try:
        resp = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=12)
        if resp.status_code != 200:
            logger.warning(f"फीड {url} वरून {resp.status_code} आला (वगळले)")
            return items
        soup = BeautifulSoup(resp.content, 'xml')
        entries = soup.find_all('item')
        if not entries:
            entries = soup.find_all('entry')
        
        for entry in entries[:MAX_ITEMS_PER_FEED]:
            title_tag = entry.find('title')
            title = title_tag.text.strip() if title_tag else ""
            if not title:
                continue
            
            link_tag = entry.find('link')
            if link_tag:
                link = link_tag.get('href') if link_tag.get('href') else link_tag.text.strip()
            else:
                link = ""
            
            pub_tag = entry.find('pubDate') or entry.find('published') or entry.find('updated')
            pub_str = pub_tag.text.strip() if pub_tag else ""
            if pub_str:
                try:
                    pub_dt = parsedate_to_datetime(pub_str)
                    if pub_dt.tzinfo is None:
                        pub_dt = pub_dt.replace(tzinfo=timezone.utc)
                except:
                    pub_dt = datetime.now(timezone.utc)
            else:
                pub_dt = datetime.now(timezone.utc)
            
            age = (datetime.now(timezone.utc) - pub_dt).total_seconds()
            if age > NEWS_AGE_LIMIT:
                continue
            
            sentiment, score = analyze_sentiment(title)
            symbol, display_name = extract_single_stock_symbol(title)
            
            if abs(score) < MIN_SENTIMENT_SCORE:
                continue
            
            if symbol:
                items.append({
                    'title': title,
                    'link': link,
                    'sentiment': sentiment,
                    'score': score,
                    'symbol': symbol,
                    'display_name': display_name,
                    'time': pub_dt.strftime('%I:%M %p'),
                    'type': 'stock',
                    'pub_time': pub_dt
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
                    'pub_time': pub_dt
                })
    except Exception as e:
        logger.error(f"फीड वाचताना एरर {url}: {e}")
    return items

# ==================== स्कॅनर आणि ग्रुपिंग ====================
def scan_news():
    stock_news = []
    macro_news = []
    for feed in ALL_FEEDS:
        items = fetch_feed(feed)
        for item in items:
            # डुप्लिकेट तपासा
            if news_exists(item['title'], item['link']):
                continue
            if item['type'] == 'stock':
                stock_news.append(item)
            else:
                macro_news.append(item)
        domain = feed.split('/')[2]
        logger.info(f"📡 {domain} वरून स्टॉक: {len([i for i in items if i['type']=='stock'])}, मॅक्रो: {len([i for i in items if i['type']=='macro'])} बातम्या मिळाल्या")
        time.sleep(0.5)
    return stock_news, macro_news

def process_and_send_news(stock_news: List[Dict], macro_news: List[Dict]):
    """ग्रुपिंग + वॉचलिस्ट प्राधान्य + LTP + मार्केट मूड"""
    global seen_stocks  # हा सेट स्कॅन सत्रात राहतो

    # ========== १) स्टॉक बातम्या ग्रुप करा ==========
    stock_groups = {}  # symbol -> list of items
    for item in stock_news:
        symbol = item['symbol']
        if symbol not in stock_groups:
            stock_groups[symbol] = []
        stock_groups[symbol].append(item)

    # ========== २) प्रत्येक ग्रुपसाठी अलर्ट ==========
    for symbol, items in stock_groups.items():
        # वॉचलिस्ट तपासा
        is_watchlist = symbol.split('.')[0] in WATCHLIST

        # एका ग्रुपमधील बातम्या क्रमवारीत लावा (जुन्या ते नवीन)
        items_sorted = sorted(items, key=lambda x: x['pub_time'])

        # पहिली बातमी (पूर्ण तपशीलवार) – फक्त जर पहिल्यांदा असेल
        # आम्ही `seen_stocks` वापरतो
        if symbol not in seen_stocks:
            # पहिल्यांदा – पूर्ण अलर्ट
            first_item = items_sorted[0]
            send_news_item(first_item, is_first=True, show_ltp=True)
            seen_stocks.add(symbol)
            # उरलेल्या बातम्या (जर असतील तर) – एक-ओळ (रिपीट)
            for item in items_sorted[1:]:
                send_news_item(item, is_first=False, show_ltp=True)
                time.sleep(0.3)
        else:
            # हा स्टॉक आधी आला आहे – सर्व बातम्या एक-ओळ (रिपीट)
            for item in items_sorted:
                send_news_item(item, is_first=False, show_ltp=True)
                time.sleep(0.3)

        # ========== ३) प्रत्येक बातमी DB मध्ये सेव्ह करा ==========
        for item in items_sorted:
            insert_news(item)

    # ========== ४) मॅक्रो बातम्या ==========
    if macro_news:
        macro_msg = "🌍 <b>मॅक्रो/ग्लोबल डायजेस्ट</b>\n"
        macro_msg += "─────────────────────\n"
        for item in macro_news[:5]:
            macro_msg += f"{item['sentiment']} (Score: {item['score']:+d}) {item['display_name']}\n"
            macro_msg += f"🕐 {item['time']}\n"
            macro_msg += f"🔗 <a href='{item['link']}'>{item['title'][:100]}{'...' if len(item['title'])>100 else ''}</a>\n"
            macro_msg += "─────────────────────\n"
            insert_news(item)
        send_telegram_alert(macro_msg, disable_preview=False)

    # ========== ५) मार्केट मूड (सरासरी स्कोअर) ==========
    all_items = stock_news + macro_news
    if all_items:
        avg_score = sum(item['score'] for item in all_items) / len(all_items)
        if avg_score >= 1.5:
            mood = "🟢 तेजी (Bullish)"
            mood_emoji = "🐂"
        elif avg_score <= -1.5:
            mood = "🔴 मंदी (Bearish)"
            mood_emoji = "🐻"
        else:
            mood = "⚪ तटस्थ (Neutral)"
            mood_emoji = "➡️"
        mood_msg = f"📊 <b>बाजार मूड</b> {mood_emoji}\n"
        mood_msg += f"📈 सरासरी स्कोअर: {avg_score:.2f}\n"
        mood_msg += f"📊 भावना: {mood}"
        send_telegram_alert(mood_msg, disable_preview=False)

# ==================== मुख्य लूप ====================
def main():
    global seen_stocks
    seen_stocks = set()  # स्कॅन सत्रासाठी
    init_db()
    logger.info("🚀 अल्टिमेट न्यूज बॉट सुरू होत आहे (सर्व स्मार्ट सुधारणांसह)...")
    send_telegram_alert("🎯 <b>अल्टिमेट न्यूज बॉट सक्रिय</b>\n✅ ८+ फीड्स\n✅ ग्रुप डायजेस्ट\n✅ LTP दाखवा\n✅ वॉचलिस्टला प्राधान्य\n✅ मार्केट मूड\n✅ SQLite स्टोअर")
    
    while True:
        try:
            logger.info("🔄 स्कॅन सुरू आहे...")
            stock_news, macro_news = scan_news()
            
            # डुप्लिकेट शीर्षक वगळा (DB आधीच करतो, पण तरीही)
            unique_stock = []
            seen_titles = set()
            for item in stock_news:
                key = item['title'].lower()
                if key not in seen_titles:
                    seen_titles.add(key)
                    unique_stock.append(item)
            unique_macro = []
            seen_macro = set()
            for item in macro_news:
                key = item['title'].lower()
                if key not in seen_macro:
                    seen_macro.add(key)
                    unique_macro.append(item)
            
            logger.info(f"📊 नवीन: {len(unique_stock)} स्टॉक, {len(unique_macro)} मॅक्रो")
            
            if unique_stock or unique_macro:
                process_and_send_news(unique_stock, unique_macro)
            else:
                logger.info("ℹ️ पाठवण्यासाठी नवीन बातम्या नाहीत.")
                
        except Exception as e:
            logger.error(f"🔥 मुख्य लूप एरर: {e}")
        
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()
