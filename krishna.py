import io
import json
import logging
import os
import re
import sys
import threading
import time
import warnings
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime

from bs4 import BeautifulSoup
from flask import Flask
import pandas as pd
import requests
import yfinance as yf

import matplotlib
matplotlib.use("Agg")

from ta.momentum import RSIIndicator
from ta.trend import EMAIndicator
from ta.volatility import AverageTrueRange

# 🔇 वॉर्निंग्ज आणि yfinance एरर्स पूर्णपणे बंद
warnings.simplefilter(action="ignore", category=FutureWarning)
warnings.filterwarnings("ignore")
logging.getLogger("yfinance").setLevel(logging.CRITICAL)


class SuppressStdout:
    def __enter__(self):
        self._original_stdout = sys.stdout
        self._original_stderr = sys.stderr
        sys.stdout = io.StringIO()
        sys.stderr = io.StringIO()

    def __exit__(self, exc_type, exc_val, exc_tb):
        sys.stdout = self._original_stdout
        sys.stderr = self._original_stderr


# ==================== CONFIGURATION ====================
TELEGRAM_BOT_TOKEN = "8634800722:AAESXRx8Xx3i1mqQvJCsh8ecLd0eP3kPdJQ"
TELEGRAM_CHAT_ID = "1106122116"
CHECK_INTERVAL = 20  # दर २० सेकंदांनी लाईव्ह स्कॅन

IST = timezone(timedelta(hours=5, minutes=30))

INDICES_MAP = {
    "^NSEI": "NIFTY 50",
    "^NSEBANK": "BANK NIFTY",
    "^BSESN": "SENSEX",
}

# 🏢 १००+ विस्तारीत स्टॉक्स डिक्शनरी
STOCKS_MAP = {
    "TATA MOTORS": "TATAMOTORS.NS", "TATAMOTORS": "TATAMOTORS.NS", "MARUTI": "MARUTI.NS",
    "MAHINDRA": "M&M.NS", "M&M": "M&M.NS", "HERO MOTOCORP": "HEROMOTOCO.NS", "EICHER": "EICHERMOT.NS",
    "TVS MOTOR": "TVSMOTOR.NS", "BAJAJ AUTO": "BAJAJ-AUTO.NS", "BHARAT FORGE": "BHARATFORG.NS",
    
    "INFOSYS": "INFY.NS", "INFY": "INFY.NS", "TCS": "TCS.NS", "WIPRO": "WIPRO.NS", "TECH MAHINDRA": "TECHM.NS",
    "HCL TECH": "HCLTECH.NS", "LTIMINDTREE": "LTIM.NS", "COFORGE": "COFORGE.NS", "PERSISTENT": "PERSISTENT.NS",
    
    "HDFC BANK": "HDFCBANK.NS", "HDFCBANK": "HDFCBANK.NS", "ICICI BANK": "ICICIBANK.NS", "ICICIBANK": "ICICIBANK.NS",
    "AXIS BANK": "AXISBANK.NS", "AXISBANK": "AXISBANK.NS", "KOTAK BANK": "KOTAKBANK.NS", "KOTAK": "KOTAKBANK.NS",
    "STATE BANK": "SBIN.NS", "SBI": "SBIN.NS", "SBIN": "SBIN.NS", "BANK OF BARODA": "BANKBARODA.NS",
    "PNB": "PNB.NS", "CANARA BANK": "CANBK.NS", "IDFC FIRST": "IDFCFIRSTB.NS", "FEDERAL BANK": "FEDERALBNK.NS",
    
    "BAJAJ FINANCE": "BAJFINANCE.NS", "BAJFINANCE": "BAJFINANCE.NS", "BAJAJ FINSERV": "BAJAJFINSV.NS",
    "JIO FINANCIAL": "JIOFIN.NS", "REC": "RECLTD.NS", "PFC": "PFC.NS", "CHOLAMANDALAM": "CHOLAFIN.NS",
    "MUTHOOT FINANCE": "MUTHOOTFIN.NS", "SHRIRAM FINANCE": "SHRIRAMFIN.NS",
    
    "RELIANCE": "RELIANCE.NS", "NTPC": "NTPC.NS", "POWER GRID": "POWERGRID.NS", "ONGC": "ONGC.NS",
    "COAL INDIA": "COALINDIA.NS", "ADANI GREEN": "ADANIGREEN.NS", "ADANI POWER": "ADANIPOWER.NS",
    "TATA POWER": "TATAPOWER.NS", "BPCL": "BPCL.NS", "IOC": "IOC.NS", "GAIL": "GAIL.NS", "SUZLON": "SUZLON.NS",
    
    "TATA STEEL": "TATASTEEL.NS", "HINDALCO": "HINDALCO.NS", "JINDAL STEEL": "JINDALSTEL.NS",
    "JSW STEEL": "JSWSTEEL.NS", "VEDANTA": "VEDL.NS", "NMDC": "NMDC.NS",
    
    "HAL": "HAL.NS", "HINDUSTAN AERONAUTICS": "HAL.NS", "BEL": "BEL.NS", "MAZAGON": "MAZDOCK.NS",
    "COCHIN SHIPYARD": "COCHINSHIP.NS", "LARSEN": "LT.NS", "L&T": "LT.NS", "SIEMENS": "SIEMENS.NS", "ABB": "ABB.NS",
    
    "TRENT": "TRENT.NS", "DIXON": "DIXON.NS", "BHARTI AIRTEL": "BHARTIARTL.NS", "AIRTEL": "BHARTIARTL.NS",
    "ITC": "ITC.NS", "TITAN": "TITAN.NS", "ASIAN PAINTS": "ASIANPAINT.NS", "ULTRATECH": "ULTRACEMCO.NS",
    "GRASIM": "GRASIM.NS", "NESTLE": "NESTLEIND.NS", "BRITANNIA": "BRITANNIA.NS", "VARUN BEVERAGES": "VBL.NS",
    "DABUR": "DABUR.NS", "GODREJ CONSUMER": "GODREJCP.NS",
    
    "ZOMATO": "ZOMATO.NS", "PAYTM": "PAYTM.NS", "POLICYBAZAAR": "POLICYBZR.NS", "DELHIVERY": "DELHIVERY.NS",
    
    "SUN PHARMA": "SUNPHARMA.NS", "CIPLA": "CIPLA.NS", "DR REDDY": "DRREDDY.NS", "DIVIS LAB": "DIVISLAB.NS",
    "LUPIN": "LUPIN.NS", "APOLLO HOSPITALS": "APOLLOHOSP.NS", "MANKIND": "MANKIND.NS",
    
    "DLF": "DLF.NS", "LODHA": "LODHA.NS", "GODREJ PROP": "GODREJPROP.NS", "INDIGO": "INDIGO.NS",
    "BSE": "BSE.NS", "ANGEL ONE": "ANGELONE.NS", "CDSL": "CDSL.NS"
}

INDIAN_NEWS_FEEDS = [
    "https://economictimes.indiatimes.com/markets/stocks/rssfeeds/2146842.cms",
    "https://www.moneycontrol.com/rss/marketreports.xml",
    "https://www.moneycontrol.com/rss/MCtopnews.xml",
    "https://www.moneycontrol.com/rss/business.xml",
    "https://www.livemint.com/rss/markets",
    "https://www.business-standard.com/rss/markets-106.rss",
    "https://www.cnbctv18.com/commonfeeds/v1/cne/rss/market.xml"
]

GLOBAL_NEWS_FEEDS = [
    "https://search.cnbc.com/rs/search/combinedrenderer.view?query=market&partnerId=2000&target=all",
    "https://feeds.a.dj.com/rss/RSSMarketsMain.xml",
    "https://www.investing.com/rss/news.rss"
]

# CACHE AND LOGGING STATES
last_signal_state = {}
seen_news_titles = set()
news_watched_stocks = set()

day_news_log = []
day_plus_signals_log = []
global_news_log = []

last_sent_910_date = ""
last_sent_330_date = ""

flask_app = Flask("")

@flask_app.route("/")
def home():
    return "⚡ Shambhu's Live Radar Engine Active! ⚡"

def run_server():
    port = int(os.environ.get("PORT", 8080))
    flask_app.run(host="0.0.0.0", port=port)

def send_telegram_alert(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Telegram API Error: {e}")

def normalize_text(text):
    """स्पेशल कॅरेक्टर्स आणि स्पेस काढून युनिक स्ट्रिंग बनवते"""
    return re.sub(r'[^a-zA-Z0-9]', '', text.lower())

def parse_exact_pub_date(pub_date_str):
    if not pub_date_str:
        return datetime.now(IST)
    try:
        dt = parsedate_to_datetime(pub_date_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(IST)
    except Exception:
        return datetime.now(IST)

def get_accurate_price(symbol):
    with SuppressStdout():
        try:
            t = yf.Ticker(symbol)
            price = getattr(t.fast_info, "last_price", None)
            if price and not pd.isna(price) and price > 0:
                return float(price)
            df = t.history(period="1d", interval="1m")
            if not df.empty:
                return float(df["Close"].iloc[-1])
        except Exception:
            pass
    return 0.0

def calculate_strike_price(index_name, current_price, option_type="CE"):
    step = 50 if "NIFTY 50" in index_name else 100
    atm_strike = round(current_price / step) * step
    return f"{atm_strike} {option_type}"

def analyze_sentiment(title):
    t = title.lower()
    bullish_kw = [
        "surge", "jump", "rally", "gain", "profit", "up", "growth", "deal", "order", 
        "record", "high", "buy", "rise", "soar", "win", "bullish", "approved", "target", 
        "dividend", "results", "revenue", "beat", "positive"
    ]
    bearish_kw = [
        "plunge", "drop", "fall", "loss", "down", "slump", "crash", "fine", "penalty", 
        "low", "cut", "slash", "bearish", "raid", "resigns", "probe", "debt", "miss", "weak", "negative"
    ]

    bull_score = sum(1 for k in bullish_kw if k in t)
    bear_score = sum(1 for k in bearish_kw if k in t)

    if bull_score > bear_score:
        return "🟢 POSITIVE", bull_score
    elif bear_score > bull_score:
        return "🔴 NEGATIVE", bear_score
    
    return "⚪ NEUTRAL", 0


# ==================== STRICT SINGLE STOCK FILTER ====================
def extract_single_stock_only(title):
    """जर हेडलाईनमध्ये फक्त आणि फक्त १च ठराविक स्टॉक असेल तरच निवडतो"""
    upper_title = title.upper()
    found_matches = set()
    
    for key, symbol in STOCKS_MAP.items():
        pattern = r"(?<![A-Z0-9])" + re.escape(key) + r"(?![A-Z0-9])"
        if re.search(pattern, upper_title):
            found_matches.add((key, symbol))

    unique_symbols = set(item[1] for item in found_matches)
    
    if len(unique_symbols) == 1:
        single_item = list(found_matches)[0]
        return single_item[0], single_item[1]
    
    return None, None


# ==================== 1. CLEAR GLOBAL SENTIMENT ENGINE ====================
def fetch_clear_global_sentiment():
    global global_news_log
    headers = {"User-Agent": "Mozilla/5.0"}
    
    pos_score, neg_score = 0, 0
    headlines = []

    for url in GLOBAL_NEWS_FEEDS:
        try:
            resp = requests.get(url, headers=headers, timeout=6)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.content, "xml")
                items = soup.find_all("item")
                if not items:
                    soup = BeautifulSoup(resp.content, "html.parser")
                    items = soup.find_all("item")

                for item in items[:5]:
                    title = item.title.text.strip() if item.title else ""
                    if title and title not in headlines:
                        headlines.append(title)
                        sent, intensity = analyze_sentiment(title)
                        if "POSITIVE" in sent:
                            pos_score += (intensity + 1)
                        elif "NEGATIVE" in sent:
                            neg_score += (intensity + 1)
        except Exception:
            pass

    net_score = pos_score - neg_score
    if net_score >= 2:
        status = "🟢 POSITIVE (BULLISH)"
    elif net_score <= -2:
        status = "🔴 NEGATIVE (BEARISH)"
    else:
        status = "🟡 NEUTRAL (SIDEWAYS)"

    top_title = headlines[0] if headlines else "Global markets stable"
    
    sentiment_obj = {
        "status": status,
        "score": net_score,
        "headline": top_title,
        "time": datetime.now(IST).strftime("%I:%M %p")
    }
    global_news_log.append(sentiment_obj)
    return sentiment_obj


# ==================== 2. ACCURATE 3-MIN TECHNICAL SCANNER ====================
def check_3min_plus_signal(symbol, display_name, is_index=False):
    global last_signal_state

    with SuppressStdout():
        try:
            ticker = yf.Ticker(symbol)
            df_stock = ticker.history(period="2d", interval="1m")
            if df_stock.empty or len(df_stock) < 15:
                return None

            df = (
                df_stock.resample("3min")
                .agg({
                    "Open": "first",
                    "High": "max",
                    "Low": "min",
                    "Close": "last",
                    "Volume": "sum",
                })
                .dropna()
            )

            if len(df) < 10:
                return None

            df["Close"] = df["Close"].values.flatten().astype(float)
            df["High"] = df["High"].values.flatten().astype(float)
            df["Low"] = df["Low"].values.flatten().astype(float)
            df["Volume"] = df["Volume"].values.flatten().astype(float)

            df["EMA_9"] = EMAIndicator(close=df["Close"], window=9).ema_indicator()
            df["EMA_26"] = EMAIndicator(close=df["Close"], window=26).ema_indicator()
            df["ATR_14"] = AverageTrueRange(high=df["High"], low=df["Low"], close=df["Close"], window=14).average_true_range()
            df["RSI_14"] = RSIIndicator(close=df["Close"], window=14).rsi()
            df["Vol_SMA"] = df["Volume"].rolling(window=20).mean()

            row_prev = df.iloc[-2]
            row_now = df.iloc[-1]

            current_close = get_accurate_price(symbol)
            if current_close == 0.0:
                current_close = float(row_now["Close"])

            atr_val = float(row_now["ATR_14"]) if not pd.isna(row_now["ATR_14"]) else current_close * 0.005
            rsi_val = float(row_now["RSI_14"])
            current_vol = float(row_now["Volume"])
            vol_sma = float(row_now["Vol_SMA"]) if not pd.isna(row_now["Vol_SMA"]) else 0.0

            volume_passed = True
            vol_ratio = 1.0
            if not is_index:
                volume_passed = (current_vol >= vol_sma) if vol_sma > 0 else True
                vol_ratio = (current_vol / vol_sma) if vol_sma > 0 else 1.0

            now_ema9 = float(row_now["EMA_9"])
            now_ema26 = float(row_now["EMA_26"])
            prev_ema9 = float(row_prev["EMA_9"])
            prev_ema26 = float(row_prev["EMA_26"])

            is_bullish_now = (now_ema9 > now_ema26) and (rsi_val >= 50) and volume_passed
            is_bearish_now = (now_ema9 < now_ema26) and (rsi_val <= 50) and volume_passed

            fresh_bullish = is_bullish_now and (prev_ema9 <= prev_ema26)
            fresh_bearish = is_bearish_now and (prev_ema9 >= prev_ema26)

            current_direction = "BULLISH" if is_bullish_now else ("BEARISH" if is_bearish_now else "NONE")
            prev_direction = last_signal_state.get(symbol, "NONE")

            is_fresh_signal = (fresh_bullish or fresh_bearish) and (current_direction != prev_direction)

            if is_fresh_signal and current_direction != "NONE":
                last_signal_state[symbol] = current_direction

                action = "BUY / CALL (CE)" if current_direction == "BULLISH" else "BUY / PUT (PE)"
                opt_type = "CE" if current_direction == "BULLISH" else "PE"

                if current_direction == "BULLISH":
                    stop_loss = current_close - (atr_val * 1.5)
                    target = current_close + ((current_close - stop_loss) * 1.5)
                else:
                    stop_loss = current_close + (atr_val * 1.5)
                    target = current_close - ((stop_loss - current_close) * 1.5)

                suggested_strike = calculate_strike_price(display_name, current_close, opt_type) if is_index else "N/A"

                condition_score = 1
                if (current_direction == "BULLISH" and rsi_val >= 60) or (current_direction == "BEARISH" and rsi_val <= 40):
                    condition_score += 2
                else:
                    condition_score += 1

                if vol_ratio >= 1.5:
                    condition_score += 2
                elif volume_passed:
                    condition_score += 1

                sig_obj = {
                    "name": display_name,
                    "direction": current_direction,
                    "sentiment": f"{'🟢' if current_direction == 'BULLISH' else '🔴'} {current_direction} PLUS (+) SIGN",
                    "action": action,
                    "price": current_close,
                    "sl": stop_loss,
                    "target": target,
                    "rsi": rsi_val,
                    "strike": suggested_strike,
                    "vol_status": f"📈 Index Signal" if is_index else f"✅ High Vol ({vol_ratio:.1f}x SMA)",
                    "score": condition_score,
                    "time": datetime.now(IST).strftime("%I:%M:%S %p")
                }

                day_plus_signals_log.append(sig_obj)
                return sig_obj

            else:
                last_signal_state[symbol] = current_direction

        except Exception:
            pass

    return None


# ==================== 3. REALTIME NO-DUPLICATE STOCK NEWS SCANNER ====================
def fetch_and_collect_stock_news():
    global seen_news_titles, news_watched_stocks, day_news_log
    headers = {"User-Agent": "Mozilla/5.0"}
    new_news_items = []

    for rss_url in INDIAN_NEWS_FEEDS:
        try:
            resp = requests.get(rss_url, headers=headers, timeout=8)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.content, "xml")
                items = soup.find_all("item")
                if not items:
                    soup = BeautifulSoup(resp.content, "html.parser")
                    items = soup.find_all("item")

                for item in items[:20]:
                    title = item.title.text.strip() if item.title else ""
                    link = item.link.text.strip() if item.link else ""
                    pub_date_raw = item.pubDate.text.strip() if item.pubDate else ""

                    exact_pub_time = parse_exact_pub_date(pub_date_raw)
                    pub_time_formatted = exact_pub_time.strftime("%I:%M:%S %p")

                    if title:
                        norm_title = normalize_text(title)

                        if norm_title not in seen_news_titles:
                            display_name, yf_symbol = extract_single_stock_only(title)
                            
                            if display_name and yf_symbol:
                                stock_news_key = f"{yf_symbol}_{norm_title}"
                                
                                if stock_news_key not in seen_news_titles:
                                    sentiment, intensity = analyze_sentiment(title)

                                    if "NEUTRAL" not in sentiment:
                                        seen_news_titles.add(norm_title)
                                        seen_news_titles.add(stock_news_key)
                                        news_watched_stocks.add((display_name, yf_symbol))

                                        price = get_accurate_price(yf_symbol)
                                        news_match_score = intensity + 1

                                        news_obj = {
                                            "stock": display_name,
                                            "symbol": yf_symbol,
                                            "price": price,
                                            "title": title,
                                            "sentiment": sentiment,
                                            "score": news_match_score,
                                            "time": pub_time_formatted,
                                            "link": link
                                        }

                                        day_news_log.append(news_obj)
                                        new_news_items.append(news_obj)

        except Exception:
            pass

    if len(new_news_items) > 5:
        new_news_items = sorted(new_news_items, key=lambda x: x["score"], reverse=True)[:5]

    return new_news_items


# ==================== 4. 09:10 AM DAILY NEWS TABLE REPORT ====================
def send_910_am_table_report():
    now_ist = datetime.now(IST)
    headers = {"User-Agent": "Mozilla/5.0"}
    news_24h = []

    for rss_url in INDIAN_NEWS_FEEDS:
        try:
            resp = requests.get(rss_url, headers=headers, timeout=8)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.content, "xml")
                items = soup.find_all("item")
                if not items:
                    soup = BeautifulSoup(resp.content, "html.parser")
                    items = soup.find_all("item")

                for item in items[:30]:
                    title = item.title.text.strip() if item.title else ""
                    pub_date_str = item.pubDate.text.strip() if item.pubDate else ""

                    pub_dt = parse_exact_pub_date(pub_date_str)
                    is_within_24h = (now_ist - pub_dt) <= timedelta(hours=24)

                    if is_within_24h and title:
                        display_name, yf_symbol = extract_single_stock_only(title)
                        if display_name and yf_symbol:
                            sent, _ = analyze_sentiment(title)
                            if "NEUTRAL" not in sent:
                                news_24h.append({"stock": display_name, "sentiment": sent})
                                news_watched_stocks.add((display_name, yf_symbol))
        except Exception:
            pass

    unique_table = {}
    for item in news_24h:
        unique_table[item["stock"]] = item["sentiment"]

    msg = f"📊 <b>09:10 AM DAILY SPECIFIC STOCK NEWS REPORT</b> 📊\n"
    msg += f"📅 <i>{now_ist.strftime('%d-%b-%Y')}</i>\n"
    msg += "═════════════════════════\n\n"

    if unique_table:
        msg += "<pre>"
        msg += f"{'STOCK NAME':<18} | {'SENTIMENT':<10}\n"
        msg += "-----------------------------------\n"
        for st, sn in unique_table.items():
            msg += f"{st[:17]:<18} | {sn:<10}\n"
        msg += "</pre>\n\n"
        msg += f"🔍 <i>Total {len(unique_table)} specific stocks added to 3-Min Chart Radar!</i>\n"
    else:
        msg += "ℹ️ <i>No specific stock news detected in the last 24 hours.</i>\n"

    msg += "═════════════════════════\n"
    msg += "🤖 <i>Shambhu's Live Precision Radar Engine</i>"

    send_telegram_alert(msg)


# ==================== 5. 03:30 PM CLOSING SUMMARY REPORT ====================
def send_330_pm_closing_summary():
    now_ist = datetime.now(IST)

    msg = f"📊 <b>03:30 PM MARKET CLOSING SUMMARY REPORT</b> 📊\n"
    msg += f"📅 <i>{now_ist.strftime('%d-%b-%Y')}</i>\n"
    msg += "═════════════════════════\n\n"

    g_sent = fetch_clear_global_sentiment()
    msg += f"🌐 <b>GLOBAL MARKET MOOD:</b> {g_sent['status']}\n"
    msg += f"• <b>Score:</b> {g_sent['score']} | <b>Cue:</b> <i>{g_sent['headline']}</i>\n"
    msg += "\n-----------------------------------------\n\n"

    msg += "📈 <b>INDICES CLOSING PRICES:</b>\n"
    for idx_sym, idx_name in INDICES_MAP.items():
        msg += f"• <b>{idx_name}:</b> ₹{get_accurate_price(idx_sym):,.2f}\n"
    msg += "\n-----------------------------------------\n\n"

    msg += f"📰 <b>TODAY'S SPECIFIC STOCK NEWS ({len(day_news_log)}):</b>\n"
    if day_news_log:
        for item in day_news_log[-8:]:
            msg += f"• <b>#{item['stock']}</b> ({item['time']}): {item['sentiment']}\n"
            msg += f"  <i>{item['title'][:60]}...</i>\n"
            if item.get("link"):
                msg += f"  🔗 <a href='{item['link']}'>Read Article</a>\n"
    else:
        msg += "• ℹ️ No specific single-stock news tracked today.\n"
    msg += "\n-----------------------------------------\n\n"

    msg += f"🔥 <b>TODAY'S 3-MIN PLUS SIGNALS ({len(day_plus_signals_log)}):</b>\n"
    if day_plus_signals_log:
        for sig in day_plus_signals_log:
            msg += f"• <b>#{sig['name']}</b> ({sig['time']}) -> {sig['sentiment']}\n"
            msg += f"  Price: ₹{sig['price']:,.2f} | Action: {sig['action']}\n"
    else:
        msg += "• ℹ️ No 3-Min Plus Signals formed during market hours today.\n"

    msg += "\n═════════════════════════\n"
    msg += "🤖 <i>Market Closed. Radar Engine Active!</i>"

    send_telegram_alert(msg)

    day_news_log.clear()
    day_plus_signals_log.clear()
    global_news_log.clear()


# ==================== 6. MAIN LIVE SCANNER ENGINE ====================
def scan_and_alert():
    global last_sent_910_date, last_sent_330_date

    now_ist = datetime.now(IST)
    current_time = now_ist.strftime("%H:%M")
    today_date = now_ist.strftime("%Y-%m-%d")

    if current_time == "09:10" and last_sent_910_date != today_date:
        send_910_am_table_report()
        last_sent_910_date = today_date

    if current_time == "15:30" and last_sent_330_date != today_date:
        send_330_pm_closing_summary()
        last_sent_330_date = today_date

    new_news_items = fetch_and_collect_stock_news()
    detected_plus_signals = []

    for index_sym, index_name in INDICES_MAP.items():
        sig = check_3min_plus_signal(index_sym, index_name, is_index=True)
        if sig:
            detected_plus_signals.append(sig)

    for s_name, s_sym in list(news_watched_stocks):
        sig = check_3min_plus_signal(s_sym, s_name, is_index=False)
        if sig:
            detected_plus_signals.append(sig)

    if new_news_items or detected_plus_signals:
        now_str = datetime.now(IST).strftime("%d-%b-%Y | %I:%M:%S %p")

        msg = f"⚡ <b>[LIVE MARKET RADAR ALERT]</b> ⚡\n"
        msg += f"📅 <i>{now_str}</i>\n"
        msg += "═════════════════════════\n\n"

        g_cue = fetch_clear_global_sentiment()
        msg += "🌐 <b>GLOBAL MARKET MOOD:</b>\n"
        msg += f"• <b>Status:</b> {g_cue['status']}\n"
        msg += f"• <b>Net Score:</b> {g_cue['score']:+d}\n"
        msg += f"• <b>Key Headline:</b> <i>{g_cue['headline']}</i>\n"
        msg += "\n-----------------------------------------\n\n"

        msg += "📈 <b>LIVE INDICES STATUS:</b>\n"
        for idx_sym, idx_name in INDICES_MAP.items():
            p = get_accurate_price(idx_sym)
            msg += f"• <b>{idx_name}:</b> ₹{p:,.2f}\n"
        msg += "\n-----------------------------------------\n\n"

        if new_news_items:
            msg += f"📰 <b>SPECIFIC STOCK NEWS ({len(new_news_items)} Filtered):</b>\n"
            for n in new_news_items:
                msg += f"• <b>#{n['stock']}</b> (₹{n['price']:,.2f})\n"
                msg += f"  Headline: <i>{n['title']}</i>\n"
                msg += f"  Sentiment: {n['sentiment']} | Time: <i>{n['time']}</i>\n"
                if n.get("link"):
                    msg += f"  🔗 <a href='{n['link']}'>Read Full Article</a>\n"
                msg += "\n"
            msg += "-----------------------------------------\n\n"

        if detected_plus_signals:
            if len(detected_plus_signals) > 5:
                detected_plus_signals = sorted(
                    detected_plus_signals, 
                    key=lambda x: x.get("score", 0), 
                    reverse=True
                )[:5]

            msg += f"🔥 <b>3-MIN PLUS SIGN DETECTED ({len(detected_plus_signals)} Filtered):</b>\n"
            for idx, sig in enumerate(detected_plus_signals, 1):
                msg += f"<b>{idx}. #{sig['name']}</b> ({sig['sentiment']})\n"
                msg += f"   • 🏆 <b>Condition Score:</b> {sig.get('score', 1)} Points\n"
                msg += f"   • 📊 <b>Volume:</b> {sig['vol_status']}\n"
                msg += f"   • ⚡ <b>Action:</b> {sig['action']}\n"
                msg += f"   • 💰 <b>Current Price:</b> ₹{sig['price']:,.2f}\n"
                if sig['strike'] != "N/A":
                    msg += f"   • 🎯 <b>Suggested Option:</b> <code>{sig['strike']}</code>\n"
                msg += f"   • 🛑 <b>SL:</b> ₹{sig['sl']:,.2f} | 🎯 <b>Target:</b> ₹{sig['target']:,.2f}\n"
                msg += f"   • 📈 <b>RSI (3m):</b> {sig['rsi']:.1f}\n\n"

        msg += "═════════════════════════\n"
        msg += "🤖 <i>Shambhu's Live Precision Radar Engine</i>"

        send_telegram_alert(msg)


def run_startup_initialization():
    print("⏳ Initializing Radar Engine Baseline States...")
    for idx_sym, idx_name in INDICES_MAP.items():
        sig = check_3min_plus_signal(idx_sym, idx_name, is_index=True)
        if sig:
            last_signal_state[idx_sym] = sig["direction"]

    send_telegram_alert("🚀 <b>Radar Engine Active!</b>\n<i>No-Duplicate Single-Stock News & 3-Min Scanner Ready...</i>")


if __name__ == "__main__":
    print("🚀 Starting Shambhu's Ordered Radar Engine...")

    t = threading.Thread(target=run_server)
    t.daemon = True
    t.start()

    run_startup_initialization()

    while True:
        try:
            time.sleep(CHECK_INTERVAL)
            scan_and_alert()
        except Exception as e:
            print(f"Main Loop Error: {e}")
            time.sleep(10)
