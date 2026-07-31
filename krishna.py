#!/usr/bin/env python3
"""
📰 NEWS ALERT BOT - SINGLE STOCK + MACRO HIGH SCORE (आता रिपीट न्यूजसाठी वेगळा फॉरमॅट)
✅ पहिल्या बातमीसाठी पूर्ण तपशीलवार अलर्ट
✅ त्याच स्टॉकच्या पुढील बातम्यांसाठी फक्त एक-ओळ क्लिक करण्याजोगा लिंक + सेन्टिमेंट
✅ मॅक्रो/ग्लोबल हाय-स्कोअर बातम्या (>= 1) – पूर्वीप्रमाणे
✅ स्टॉक्स CSV मध्ये सेव्ह होतील
"""

import time
import requests
import re
import logging
import csv
import os
from datetime import datetime, timezone
from bs4 import BeautifulSoup
from typing import List, Dict, Optional, Tuple
from email.utils import parsedate_to_datetime

# ==================== कॉन्फिगरेशन ====================
TELEGRAM_BOT_TOKEN = '8634800722:AAESXRx8Xx3i1mqQvJCsh8ecLd0eP3kPdJQ'
TELEGRAM_CHAT_ID = '1106122116'
CHECK_INTERVAL = 60  # दर ६० सेकंदांनी स्कॅन
MAX_ITEMS_PER_FEED = 15
NEWS_AGE_LIMIT = 3600  # १ तासाच्या आतल्या बातम्या
MIN_SENTIMENT_SCORE = 1  # तात्पुरता 1 ठेवा, नंतर 3 करा
STORE_STOCKS_FILE = 'stocks_log.csv'
# =====================================================

# 📰 फक्त १००% वर्किंग फीड्स
INDIAN_NEWS_FEEDS = [
    "https://news.google.com/rss/search?q=Indian+stock+market+NIFTY+BANK+NIFTY+RELIANCE+HDFC+INFY&hl=en-IN&gl=IN&ceid=IN:en",
    "https://economictimes.indiatimes.com/markets/stocks/rssfeeds/2146842.cms",
    "https://www.livemint.com/rss/markets",
    "https://www.cnbctv18.com/commonfeeds/v1/cne/rss/market.xml",
]

GLOBAL_NEWS_FEEDS = [
    "https://feeds.a.dj.com/rss/RSSMarketsMain.xml",   # WSJ
    "https://www.investing.com/rss/news.rss",
]

ALL_FEEDS = INDIAN_NEWS_FEEDS + GLOBAL_NEWS_FEEDS

# 📊 भारतीय स्टॉक मॅप (फक्त भारतीय कंपन्या)
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

# मॅक्रो कीवर्ड (फक्त लेबलसाठी)
MACRO_KEYWORDS = [
    "rbi", "fed", "crude", "oil", "dollar", "inr", "inflation", "cpi", 
    "ppi", "gdp", "unemployment", "rate cut", "rate hike", "recession",
    "stimulus", "treasury", "yield", "bond", "forex", "rupee", "fii", "dii"
]

# सेंटिमेंट कीवर्ड (स्कोअरसाठी)
BULLISH_KEYWORDS = [
    "beats", "surge", "jump", "rally", "record high", "all-time high",
    "positive", "upgrade", "target raised", "strong growth", "buyback",
    "dividend", "bonus", "outperform", "bullish", "profit", "gain",
    "exceeds", "above estimates", "robust", "soar", "boom"
]
BEARISH_KEYWORDS = [
    "misses", "drop", "plunge", "crash", "record low", "all-time low",
    "negative", "downgrade", "target cut", "slowdown", "default",
    "fraud", "investigation", "selloff", "bearish", "loss", "decline",
    "below estimates", "weak", "slump", "tumble", "slip"
]

# ==================== लॉगिंग ====================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# ==================== टेलिग्राम ====================
def send_telegram_alert(message: str, disable_preview: bool = False):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": disable_preview
    }
    try:
        resp = requests.post(url, json=payload, timeout=10)
        if resp.status_code != 200:
            logger.error(f"टेलिग्राम एरर: {resp.text}")
    except Exception as e:
        logger.error(f"टेलिग्राम पाठवताना एरर: {e}")

# ==================== स्टॉक स्टोअर ====================
def store_stock(item: Dict):
    """स्टॉक बातमी CSV मध्ये सेव्ह करा"""
    file_exists = os.path.isfile(STORE_STOCKS_FILE)
    try:
        with open(STORE_STOCKS_FILE, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(['Timestamp', 'Stock_Symbol', 'Display_Name', 'Score', 'Sentiment', 'Title', 'Link'])
            writer.writerow([
                datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                item.get('symbol', ''),
                item.get('display_name', ''),
                item.get('score', 0),
                item.get('sentiment', ''),
                item.get('title', ''),
                item.get('link', '')
            ])
    except Exception as e:
        logger.error(f"स्टॉक स्टोअर करताना एरर: {e}")

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
    score = max(-6, min(6, score))
    
    if score >= 2:
        return "🟢 POSITIVE", score
    elif score <= -2:
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
                    'type': 'stock'
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
                    'type': 'macro'
                })
    except Exception as e:
        logger.error(f"फीड वाचताना एरर {url}: {e}")
    return items

# ==================== मुख्य स्कॅनर ====================
def scan_news():
    stock_news = []
    macro_news = []
    for feed in ALL_FEEDS:
        items = fetch_feed(feed)
        for item in items:
            if item['type'] == 'stock':
                stock_news.append(item)
            else:
                macro_news.append(item)
        domain = feed.split('/')[2]
        logger.info(f"📡 {domain} वरून स्टॉक: {len([i for i in items if i['type']=='stock'])}, मॅक्रो: {len([i for i in items if i['type']=='macro'])} बातम्या मिळाल्या")
        time.sleep(0.5)
    return stock_news, macro_news

# ==================== अलर्ट पाठवणारा (नवीन रिपीट लॉजिक) ====================
# ग्लोबल सेट – ज्या स्टॉक्सची पहिली बातमी आली आहे ते ट्रॅक करण्यासाठी
seen_stocks = set()

def process_and_send_news(stock_news: List[Dict], macro_news: List[Dict]):
    global seen_stocks

    # पहिल्यांदा येणाऱ्या स्टॉक्सची बातमी (संपूर्ण अलर्टसाठी)
    first_time_stock_news = []
    # बाकीच्या स्टॉक बातम्या (रिपीट) – थेट एक-ओळ अलर्ट पाठवायचा
    repeat_stock_news = []

    for item in stock_news:
        symbol = item['symbol']
        if symbol not in seen_stocks:
            # पहिल्यांदा – पूर्ण अलर्टसाठी ठेवा
            seen_stocks.add(symbol)
            first_time_stock_news.append(item)
        else:
            # आधी आलेला स्टॉक – रिपीट, त्यामुळे थेट एक-ओळ अलर्ट पाठवा
            repeat_stock_news.append(item)

    # ===== १) पहिल्यांदा स्टॉक + मॅक्रो बातम्या एकत्र बॅच मध्ये पाठवा (पूर्वीप्रमाणे) =====
    if first_time_stock_news or macro_news:
        msg = "🎯 <b>हाय-इम्पॅक्ट न्यूज डायजेस्ट</b> 🎯\n"
        msg += f"🕒 {datetime.now().strftime('%I:%M:%S %p')}\n"
        msg += "═════════════════════════\n"
        
        if first_time_stock_news:
            msg += "\n📌 <b>सिंगल-स्टॉक बातम्या</b>\n"
            msg += "─────────────────────\n"
            for idx, item in enumerate(first_time_stock_news[:5], 1):
                score_emoji = "💪" if abs(item['score']) >= 4 else "👍"
                msg += f"{item['sentiment']} <b>#{item['display_name']}</b> {score_emoji} (Score: {item['score']:+d})\n"
                msg += f"🕐 {item['time']}\n"
                link = item['link']
                if link:
                    msg += f"🔗 <a href='{link}'>{item['title'][:100]}{'...' if len(item['title'])>100 else ''}</a>\n"
                else:
                    msg += f"📄 {item['title'][:100]}\n"
                msg += "─────────────────────\n"
                # CSV मध्ये सेव्ह
                store_stock(item)
        
        if macro_news:
            if first_time_stock_news:
                msg += "\n🌍 <b>मॅक्रो/ग्लोबल बातम्या</b>\n"
                msg += "─────────────────────\n"
            else:
                msg += "\n🌍 <b>मॅक्रो/ग्लोबल बातम्या</b>\n"
                msg += "─────────────────────\n"
            for idx, item in enumerate(macro_news[:5], 1):
                score_emoji = "💪" if abs(item['score']) >= 4 else "👍"
                msg += f"{item['sentiment']} <b>{item['display_name']}</b> {score_emoji} (Score: {item['score']:+d})\n"
                msg += f"🕐 {item['time']}\n"
                link = item['link']
                if link:
                    msg += f"🔗 <a href='{link}'>{item['title'][:100]}{'...' if len(item['title'])>100 else ''}</a>\n"
                else:
                    msg += f"📄 {item['title'][:100]}\n"
                msg += "─────────────────────\n"
        
        msg += "\n═════════════════════════\n"
        msg += "🤖 <i>शंभूचा ड्युअल-मोड न्यूज मॉनिटर</i>"
        
        send_telegram_alert(msg, disable_preview=False)
        logger.info(f"✅ पाठवले: {len(first_time_stock_news)} पहिल्यांदा स्टॉक + {len(macro_news)} मॅक्रो बातम्या.")

    # ===== २) रिपीट स्टॉक बातम्यांसाठी स्वतंत्र एक-ओळ अलर्ट =====
    for item in repeat_stock_news:
        # एक-ओळ संदेश
        short_msg = f"📌 {item['sentiment']} <b>#{item['display_name']}</b> (Score: {item['score']:+d})\n"
        link = item['link']
        if link:
            short_msg += f"🔗 <a href='{link}'>{item['title'][:80]}{'...' if len(item['title'])>80 else ''}</a>"
        else:
            short_msg += f"📄 {item['title'][:80]}"
        send_telegram_alert(short_msg, disable_preview=False)
        # CSV मध्ये सेव्ह
        store_stock(item)
        logger.info(f"📨 रिपीट बातमी पाठवली: {item['display_name']}")
        time.sleep(0.5)  # थोडा अंतर ठेवा जेणेकरून स्पॅम होणार नाही

# ==================== मुख्य लूप ====================
def main():
    global seen_stocks  # हा सेट सत्रात कायम राहील (रन दरम्यान)
    logger.info("🚀 ड्युअल-मोड न्यूज बॉट सुरू होत आहे (स्टॉक + मॅक्रो)...")
    send_telegram_alert("🎯 <b>ड्युअल-मोड हाय-स्कोअर न्यूज बॉट सक्रिय</b>\n✅ पहिल्या बातमीसाठी पूर्ण अलर्ट\n✅ त्याच स्टॉकसाठी पुढील बातम्यांसाठी फक्त एक-ओळ लिंक + सेन्टिमेंट\n📥 स्टॉक्स CSV मध्ये सेव्ह होतील.")
    
    seen_titles = set()
    
    while True:
        try:
            logger.info("🔄 स्कॅन सुरू आहे...")
            stock_news, macro_news = scan_news()
            
            unique_stock = []
            unique_macro = []
            for item in stock_news:
                key = item['title'].lower()
                if key not in seen_titles:
                    seen_titles.add(key)
                    unique_stock.append(item)
            for item in macro_news:
                key = item['title'].lower()
                if key not in seen_titles:
                    seen_titles.add(key)
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
