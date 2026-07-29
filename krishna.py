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
from concurrent.futures import ThreadPoolExecutor

from bs4 import BeautifulSoup
from flask import Flask
import pandas as pd
import requests
import yfinance as yf

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from ta.momentum import RSIIndicator
from ta.trend import EMAIndicator
from ta.volatility import AverageTrueRange

# 🔇 वॉर्निंग्ज बंद करणे
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
CHECK_INTERVAL = 15  # दर १५ सेकंदांनी स्कॅनिंग
MAX_RISK_PER_TRADE = 1000  # एका ट्रेडमधील कमाल रिस्क (₹)

IST = timezone(timedelta(hours=5, minutes=30))

INDICES_MAP = {
    "^NSEI": "NIFTY 50",
    "^NSEBANK": "BANK NIFTY",
    "^BSESN": "SENSEX",
}

# Nifty 50 मधील मुख्य वेटेज स्टॉक्स
NIFTY_WEIGHTAGE_STOCKS = {
    "HDFC Bank": "HDFCBANK.NS",
    "Reliance": "RELIANCE.NS",
    "ICICI Bank": "ICICIBANK.NS",
    "Infosys": "INFY.NS",
    "TCS": "TCS.NS",
    "L&T": "LT.NS",
    "ITC": "ITC.NS",
    "Axis Bank": "AXISBANK.NS"
}

MACRO_TICKERS = {
    "GIFT Nifty": "^NSEI",
    "US Dow Futures": "YM=F",
    "US Nasdaq Futures": "NQ=F",
    "India VIX": "^INDIAVIX",
    "Crude Oil (WTI)": "CL=F",
    "US Dollar Index (DXY)": "DX-Y.NYB"
}

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
    "https://www.moneycontrol.com/rss/marketreports.xml",
    "https://www.moneycontrol.com/rss/MCtopnews.xml",
    "https://www.moneycontrol.com/rss/business.xml",
    "https://economictimes.indiatimes.com/markets/stocks/rssfeeds/2146842.cms",
    "https://www.livemint.com/rss/markets",
    "https://www.business-standard.com/rss/markets-106.rss",
    "https://www.cnbctv18.com/commonfeeds/v1/cne/rss/market.xml"
]

GLOBAL_NEWS_FEEDS = [
    "https://search.cnbc.com/rs/search/combinedrenderer.view?query=market&partnerId=2000&target=all",
    "https://feeds.a.dj.com/rss/RSSMarketsMain.xml",
    "https://www.investing.com/rss/news.rss"
]

# CACHE, LOGGING & WIN-RATE TRACKER STATES
last_signal_state = {}
last_alert_candle_time = {}
seen_news_titles = set()
news_watched_stocks = set()

stock_news_tracker = {}
day_news_log = []
day_plus_signals_log = []

# WIN-RATE ACCURACY STATS
TRADE_STATS = {
    "total_signals": 0,
    "target_hit": 0,
    "sl_hit": 0
}
ACTIVE_MONITORED_TRADES = []  # लाईव्ह सिग्नल टार्गेट/स्टॉपलॉस ट्रॅकिंगसाठी

last_sent_845_date = ""
last_sent_910_date = ""
last_sent_330_date = ""

flask_app = Flask("")

@flask_app.route("/")
def home():
    return "⚡ Shambhu's Live Radar Engine Active! ⚡"

def run_server():
    port = int(os.environ.get("PORT", 8080))
    flask_app.run(host="0.0.0.0", port=port)

# 🎯 TELEGRAM ALERT WITH INLINE BUTTONS SUPPORT
def send_telegram_alert(message, reply_markup=None):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
        
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Telegram API Error: {e}")

def send_telegram_photo(image_bytes, caption=""):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
    files = {"photo": ("chart.png", image_bytes, "image/png")}
    data = {"chat_id": TELEGRAM_CHAT_ID, "caption": caption, "parse_mode": "HTML"}
    try:
        requests.post(url, data=data, files=files, timeout=15)
    except Exception as e:
        print(f"Telegram Photo API Error: {e}")

def generate_chart_image(symbol, display_name):
    with SuppressStdout():
        try:
            ticker = yf.Ticker(symbol)
            df = ticker.history(period="1d", interval="3m")
            if df.empty or len(df) < 5:
                return None

            df['EMA_9'] = EMAIndicator(close=df['Close'], window=9).ema_indicator()
            df['EMA_26'] = EMAIndicator(close=df['Close'], window=26).ema_indicator()
            df['RSI_14'] = RSIIndicator(close=df['Close'], window=14).rsi()

            fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(8, 5), gridspec_kw={'height_ratios': [3, 1]}, dpi=120)

            ax1.plot(df.index, df['Close'], label='Close Price', color='#1f77b4', linewidth=1.8)
            ax1.plot(df.index, df['EMA_9'], label='EMA 9', color='#2ca02c', linestyle='--', linewidth=1.2)
            ax1.plot(df.index, df['EMA_26'], label='EMA 26', color='#d62728', linestyle='--', linewidth=1.2)
            ax1.set_title(f"📈 {display_name} - 3 Min Signal Chart", fontsize=11, fontweight='bold')
            ax1.set_ylabel("Price (₹)")
            ax1.grid(True, linestyle=':', alpha=0.6)
            ax1.legend(loc='upper left', fontsize=8)

            ax2.plot(df.index, df['RSI_14'], label='RSI (14)', color='#9467bd', linewidth=1.4)
            ax2.axhline(70, color='red', linestyle=':', alpha=0.7)
            ax2.axhline(30, color='green', linestyle=':', alpha=0.7)
            ax2.axhline(50, color='gray', linestyle='--', alpha=0.5)
            ax2.set_ylabel("RSI")
            ax2.set_ylim(0, 100)
            ax2.grid(True, linestyle=':', alpha=0.6)
            ax2.legend(loc='upper left', fontsize=7)

            buf = io.BytesIO()
            plt.tight_layout()
            plt.savefig(buf, format='png')
            buf.seek(0)
            plt.close(fig)
            return buf
        except Exception as e:
            print(f"Chart Generation Error: {e}")
            return None

def normalize_text(text):
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

def is_market_hours():
    now = datetime.now(IST)
    if now.weekday() >= 5:
        return False
    start = now.replace(hour=9, minute=15, second=0, microsecond=0)
    end = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return start <= now <= end

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

def fetch_macro_indicators():
    results = {}
    for name, sym in MACRO_TICKERS.items():
        with SuppressStdout():
            try:
                t = yf.Ticker(sym)
                df = t.history(period="2d")
                if not df.empty:
                    last_price = float(df['Close'].iloc[-1])
                    prev_price = float(df['Close'].iloc[-2]) if len(df) > 1 else last_price
                    chg_pct = ((last_price - prev_price) / prev_price) * 100 if prev_price > 0 else 0.0
                    results[name] = {"price": last_price, "change_pct": chg_pct}
                else:
                    results[name] = {"price": 0.0, "change_pct": 0.0}
            except Exception:
                results[name] = {"price": 0.0, "change_pct": 0.0}
    return results

def calculate_strike_price(index_name, current_price, option_type="CE"):
    step = 50 if "NIFTY 50" in index_name else 100
    atm_strike = round(current_price / step) * step
    return f"{atm_strike} {option_type}"

def analyze_sentiment(title):
    t = title.lower()
    bullish_kw = [
        "surge", "jump", "rally", "gain", "profit", "up", "growth", "deal", "order", 
        "record", "high", "buy", "rise", "soar", "win", "bullish", "approved", "target", 
        "dividend", "results", "revenue", "beat", "positive", "peace", "rate cut", "trade deal"
    ]
    bearish_kw = [
        "plunge", "drop", "fall", "loss", "down", "slump", "crash", "fine", "penalty", 
        "low", "cut", "slash", "bearish", "raid", "resigns", "probe", "debt", "miss", "weak", 
        "negative", "war", "trump", "crude oil", "crude", "tariff", "sanction", "conflict", 
        "inflation", "fed hike", "rate hike", "tension", "crisis"
    ]

    bull_score = sum(1 for k in bullish_kw if k in t)
    bear_score = sum(1 for k in bearish_kw if k in t)

    if bull_score > bear_score:
        return "🟢 POSITIVE", bull_score
    elif bear_score > bull_score:
        return "🔴 NEGATIVE", bear_score
    
    return "⚪ NEUTRAL", 0

def extract_single_stock_only(title):
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

def fetch_clickable_global_news_list():
    headers = {"User-Agent": "Mozilla/5.0"}
    news_items = []

    for url in GLOBAL_NEWS_FEEDS:
        try:
            resp = requests.get(url, headers=headers, timeout=6)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.content, "xml")
                items = soup.find_all("item")
                if not items:
                    soup = BeautifulSoup(resp.content, "html.parser")
                    items = soup.find_all("item")

                for item in items[:6]:
                    title = item.title.text.strip() if item.title else ""
                    link = item.link.text.strip() if item.link else ""
                    if title and link:
                        sent, _ = analyze_sentiment(title)
                        news_items.append({
                            "title": title,
                            "link": link,
                            "sentiment": sent
                        })
        except Exception:
            pass
            
    return news_items[:5]

# 🎯 WIN-RATE ACCURACY LOGIC
def update_and_check_trade_outcomes():
    """दिवसभरातील सिग्नलचे Target Hit किंवा SL Hit ऑटो-चेक करणे"""
    global ACTIVE_MONITORED_TRADES, TRADE_STATS
    if not is_market_hours() or not ACTIVE_MONITORED_TRADES:
        return

    updated_list = []
    for trade in ACTIVE_MONITORED_TRADES:
        curr_price = get_accurate_price(trade["symbol"])
        if curr_price == 0.0:
            updated_list.append(trade)
            continue

        target_hit = False
        sl_hit = False

        if trade["direction"] == "BULLISH":
            if curr_price >= trade["target"]:
                target_hit = True
            elif curr_price <= trade["sl"]:
                sl_hit = True
        else:
            if curr_price <= trade["target"]:
                target_hit = True
            elif curr_price >= trade["sl"]:
                sl_hit = True

        if target_hit:
            TRADE_STATS["target_hit"] += 1
        elif sl_hit:
            TRADE_STATS["sl_hit"] += 1
        else:
            updated_list.append(trade)

    ACTIVE_MONITORED_TRADES = updated_list

def get_win_rate_summary_text():
    total = TRADE_STATS["total_signals"]
    hits = TRADE_STATS["target_hit"]
    sls = TRADE_STATS["sl_hit"]
    closed = hits + sls
    win_rate = (hits / closed * 100) if closed > 0 else 0.0
    
    return (
        f"📊 <b>TODAY'S ACCURACY & WIN-RATE STATS:</b>\n"
        f"• Total Signals: <b>{total}</b>\n"
        f"• Target Hit: <b>{hits}</b> ✅ | SL Hit: <b>{sls}</b> ❌\n"
        f"• Win Rate Accuracy: <b>{win_rate:.1f}%</b> 🎯\n"
    )

# 🎯 ORIGINAL CORE SIGNAL LOGIC (NO FILTER CHANGE + ADDED INFO DETAILS)
def check_3min_plus_signal(symbol, display_name, is_index=False):
    global last_signal_state, last_alert_candle_time

    with SuppressStdout():
        try:
            ticker = yf.Ticker(symbol)
            df = ticker.history(period="1d", interval="3m")
            if df.empty or len(df) < 5:
                return None

            df["Close"] = df["Close"].values.flatten().astype(float)
            df["High"] = df["High"].values.flatten().astype(float)
            df["Low"] = df["Low"].values.flatten().astype(float)
            df["Volume"] = df["Volume"].values.flatten().astype(float)

            # --- ORIGINAL INDICATORS ---
            df["EMA_9"] = EMAIndicator(close=df["Close"], window=9).ema_indicator()
            df["EMA_26"] = EMAIndicator(close=df["Close"], window=26).ema_indicator()
            df["ATR_14"] = AverageTrueRange(high=df["High"], low=df["Low"], close=df["Close"], window=14).average_true_range()
            df["RSI_14"] = RSIIndicator(close=df["Close"], window=14).rsi()
            df["Vol_SMA"] = df["Volume"].rolling(window=20).mean()

            # 📌 INFO ONLY: VWAP & SUPERTREND (नो अलर्ट फिल्टरिंग)
            tp = (df["High"] + df["Low"] + df["Close"]) / 3
            df["VWAP"] = (tp * df["Volume"]).cumsum() / df["Volume"].cumsum()
            current_vwap = round(float(df["VWAP"].iloc[-1]), 2) if not df["VWAP"].empty else float(df["Close"].iloc[-1])
            
            latest_close = float(df["Close"].iloc[-1])
            vwap_info = f"Above VWAP (₹{current_vwap}) 🟢" if latest_close >= current_vwap else f"Below VWAP (₹{current_vwap}) 🔴"
            
            atr_temp = float(df["ATR_14"].iloc[-1]) if not pd.isna(df["ATR_14"].iloc[-1]) else 1.0
            st_val = round(latest_close - (atr_temp * 2), 2) if latest_close >= current_vwap else round(latest_close + (atr_temp * 2), 2)
            supertrend_info = f"Bullish (₹{st_val}) 🟢" if latest_close >= current_vwap else f"Bearish (₹{st_val}) 🔴"

            row_prev = df.iloc[-2] if len(df) >= 2 else df.iloc[-1]
            row_now = df.iloc[-1]
            candle_timestamp = str(df.index[-1])

            current_close = get_accurate_price(symbol)
            if current_close == 0.0:
                current_close = float(row_now["Close"])

            atr_val = float(row_now["ATR_14"]) if not pd.isna(row_now["ATR_14"]) else current_close * 0.005
            rsi_val = float(row_now["RSI_14"]) if not pd.isna(row_now["RSI_14"]) else 50.0
            current_vol = float(row_now["Volume"])
            vol_sma = float(row_now["Vol_SMA"]) if not pd.isna(row_now["Vol_SMA"]) else 0.0

            vol_ratio = (current_vol / vol_sma) if vol_sma > 0 else 1.0

            warning_note = ""
            if vol_ratio < 1.0 and not is_index:
                warning_note = "⚠️ Volume is low (<1.0x SMA), please trade carefully!"
            elif vol_ratio >= 2.0 and not is_index:
                warning_note = "🔥 High Volume Confirmation (>2.0x SMA)!"
            else:
                warning_note = "✅ Volume Normal."

            now_ema9 = float(row_now["EMA_9"])
            now_ema26 = float(row_now["EMA_26"])
            prev_ema9 = float(row_prev["EMA_9"])
            prev_ema26 = float(row_prev["EMA_26"])

            # 🎯 exact original signal conditions preserved
            is_bullish_now = (now_ema9 > now_ema26) and (rsi_val >= 50)
            is_bearish_now = (now_ema9 < now_ema26) and (rsi_val <= 50)

            fresh_bullish = is_bullish_now and (prev_ema9 <= prev_ema26)
            fresh_bearish = is_bearish_now and (prev_ema9 >= prev_ema26)

            current_direction = "BULLISH" if is_bullish_now else ("BEARISH" if is_bearish_now else "NONE")
            prev_direction = last_signal_state.get(symbol, "NONE")

            is_fresh_signal = (fresh_bullish or fresh_bearish) or (current_direction != "NONE" and prev_direction == "NONE")

            if is_fresh_signal and current_direction != "NONE":
                if last_alert_candle_time.get(symbol) == candle_timestamp:
                    return None

                last_signal_state[symbol] = current_direction
                last_alert_candle_time[symbol] = candle_timestamp

                action = "BUY / CALL (CE)" if current_direction == "BULLISH" else "BUY / PUT (PE)"
                opt_type = "CE" if current_direction == "BULLISH" else "PE"

                if current_direction == "BULLISH":
                    stop_loss = current_close - (atr_val * 1.5)
                    target = current_close + ((current_close - stop_loss) * 1.5)
                else:
                    stop_loss = current_close + (atr_val * 1.5)
                    target = current_close - ((stop_loss - current_close) * 1.5)

                # 🧮 Auto Position Sizing Calculator
                risk_per_share = abs(current_close - stop_loss)
                recommended_qty = int(MAX_RISK_PER_TRADE / risk_per_share) if risk_per_share > 0 else 1

                suggested_strike = calculate_strike_price(display_name, current_close, opt_type) if is_index else "N/A"

                sig_obj = {
                    "name": display_name,
                    "symbol": symbol,
                    "direction": current_direction,
                    "sentiment": f"{'🟢' if current_direction == 'BULLISH' else '🔴'} {current_direction} PLUS (+) SIGN",
                    "action": action,
                    "price": current_close,
                    "sl": stop_loss,
                    "target": target,
                    "rsi": rsi_val,
                    "strike": suggested_strike,
                    "warning_note": warning_note,
                    "vol_ratio": f"{vol_ratio:.1f}x",
                    "time": datetime.now(IST).strftime("%I:%M:%S %p"),
                    "vwap_info": vwap_info,
                    "supertrend_info": supertrend_info,
                    "risk_per_share": risk_per_share,
                    "recommended_qty": recommended_qty
                }

                day_plus_signals_log.append(sig_obj)
                
                # Win-Rate tracker update
                TRADE_STATS["total_signals"] += 1
                ACTIVE_MONITORED_TRADES.append({
                    "symbol": symbol,
                    "direction": current_direction,
                    "target": target,
                    "sl": stop_loss
                })

                return sig_obj

            else:
                last_signal_state[symbol] = current_direction

        except Exception:
            pass

    return None

def fetch_and_collect_stock_news():
    global seen_news_titles, news_watched_stocks, day_news_log, stock_news_tracker
    headers = {"User-Agent": "Mozilla/5.0"}

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
                                    sentiment, _ = analyze_sentiment(title)

                                    if "NEUTRAL" not in sentiment:
                                        seen_news_titles.add(norm_title)
                                        seen_news_titles.add(stock_news_key)
                                        news_watched_stocks.add((display_name, yf_symbol))

                                        price = get_accurate_price(yf_symbol)
                                        
                                        if yf_symbol not in stock_news_tracker:
                                            stock_news_tracker[yf_symbol] = {"pos": 0, "neg": 0}

                                        if "POSITIVE" in sentiment:
                                            stock_news_tracker[yf_symbol]["pos"] += 1
                                        else:
                                            stock_news_tracker[yf_symbol]["neg"] += 1

                                        pos_count = stock_news_tracker[yf_symbol]["pos"]
                                        neg_count = stock_news_tracker[yf_symbol]["neg"]
                                        dots_str = ("🟢" * pos_count) + ("🔴" * neg_count)

                                        news_obj = {
                                            "stock": display_name,
                                            "symbol": yf_symbol,
                                            "price": price,
                                            "title": title,
                                            "sentiment": sentiment,
                                            "time": pub_time_formatted,
                                            "link": link,
                                            "dots": dots_str
                                        }

                                        day_news_log.append(news_obj)

                                        if is_market_hours():
                                            link_html = f'<a href="{link}">{title}</a>' if link else f'<i>{title}</i>'
                                            news_alert_msg = (
                                                f"📰 <b>LIVE STOCK NEWS ALERT</b>\n"
                                                f"🏢 <b>#{display_name}</b> | {dots_str}\n"
                                                f"═════════════════════════\n"
                                                f"• 📰 <b>Headline:</b> {link_html}\n"
                                                f"• 📊 <b>Sentiment:</b> {sentiment}\n"
                                                f"• ⏰ <b>Time:</b> {pub_time_formatted}\n"
                                                f"• 💰 <b>Price:</b> ₹{price:,.2f}\n"
                                                f"═════════════════════════\n"
                                                f"🤖 <i>Shambhu's Live Precision Radar Engine</i>"
                                            )
                                            send_telegram_alert(news_alert_msg)

        except Exception:
            pass

# 🎯 INSTANT ALERT WITH BUTTONS, RISK CALC & WIN RATE
def send_instant_plus_signal_alert(sig):
    now_str = datetime.now(IST).strftime("%d-%b-%Y | %I:%M:%S %p")
    
    matched_news = [n for n in day_news_log if n['stock'] == sig['name']]
    if matched_news:
        latest_n = matched_news[-1]
        news_html = f'<a href="{latest_n["link"]}">{latest_n["title"]}</a>' if latest_n.get('link') else f'<i>{latest_n["title"]}</i>'
        news_sent = latest_n['sentiment']
    else:
        news_html = "<i>No Recent Specific News (Pure Technical Breakout)</i>"
        news_sent = "⚪ NEUTRAL"

    win_rate_summary = get_win_rate_summary_text()

    msg = (
        f"⚡ <b>[INSTANT LIVE (+) SIGN ALERT]</b> ⚡\n"
        f"📅 <i>{now_str}</i>\n"
        f"═════════════════════════\n\n"
        f"🔥 <b>#{sig['name']}</b> ({sig['sentiment']})\n"
        f"• 📰 <b>Stock News:</b> {news_html}\n"
        f"• 📊 <b>News Sentiment:</b> {news_sent}\n"
        f"• ⚡ <b>+ Sign Status:</b> ✅ DETECTED ({sig['action']})\n"
        f"• 📢 <b>Indicator Note:</b> <i>{sig['warning_note']}</i>\n"
        f"• 📈 <b>RSI (3m):</b> {sig['rsi']:.1f}\n"
        f"• 💰 <b>Current Price:</b> ₹{sig['price']:,.2f}\n"
        f"📌 <b>Indicator Details (For Ref Only):</b>\n"
        f"• <b>VWAP:</b> {sig['vwap_info']}\n"
        f"• <b>Supertrend:</b> {sig['supertrend_info']}\n\n"
        f"🧮 <b>Risk Management (Max Risk ₹{MAX_RISK_PER_TRADE}):</b>\n"
        f"• Risk/Share: ₹{sig['risk_per_share']:.2f}\n"
        f"• Recommended Qty: <b>{sig['recommended_qty']} Shares</b>\n\n"
    )
    
    if sig['strike'] != "N/A":
        msg += f"• 🎯 <b>Suggested Option:</b> <code>{sig['strike']}</code>\n"

    msg += (
        f"• 🛑 <b>SL:</b> ₹{sig['sl']:,.2f} | 🎯 <b>Target:</b> ₹{sig['target']:,.2f}\n"
        f"═════════════════════════\n"
        f"{win_rate_summary}"
        f"═════════════════════════\n"
        f"🤖 <i>Shambhu's Live Precision Radar Engine</i>"
    )

    # 🎯 TELEGRAM INLINE BUTTONS SETUP
    clean_sym = sig['symbol'].replace('.NS', '')
    reply_markup = {
        "inline_keyboard": [
            [
                {
                    "text": "📊 Live TradingView Chart",
                    "url": f"https://in.tradingview.com/chart/?symbol=NSE:{clean_sym}"
                }
            ],
            [
                {
                    "text": "🔍 NSE Stock Details",
                    "url": f"https://www.nseindia.com/get-quotes/equity?symbol={clean_sym}"
                }
            ]
        ]
    }

    send_telegram_alert(msg, reply_markup=reply_markup)

    chart_img = generate_chart_image(sig['symbol'], sig['name'])
    if chart_img:
        caption = (
            f"📊 <b>{sig['name']}</b> ({sig['sentiment']})\n"
            f"⚡ <b>Action:</b> {sig['action']} | 💰 <b>Price:</b> ₹{sig['price']:,.2f}\n"
            f"🛑 <b>SL:</b> ₹{sig['sl']:,.2f} | 🎯 <b>Target:</b> ₹{sig['target']:,.2f}\n"
            f"📢 <i>{sig['warning_note']}</i>"
        )
        send_telegram_photo(chart_img, caption=caption)

# ==================== SCHEDULED REPORTS ====================

def send_845_am_premarket_report():
    now_ist = datetime.now(IST)
    macros = fetch_macro_indicators()
    news_items = fetch_clickable_global_news_list()

    msg = f"🌅 <b>08:45 AM PRE-MARKET MACRO RADAR REPORT</b> 🌅\n"
    msg += f"📅 <i>{now_ist.strftime('%d-%b-%Y')}</i>\n"
    msg += "═════════════════════════\n\n"

    msg += "📊 <b>GLOBAL & LEADING INDICATORS:</b>\n"
    for name, val in macros.items():
        price_str = f"{val['price']:,.2f}"
        chg_str = f"{val['change_pct']:+.2f}%"
        icon = "🟢" if val['change_pct'] >= 0 else "🔴"
        msg += f"• <b>{name}:</b> {price_str} ({icon} {chg_str})\n"

    msg += "\n-----------------------------------------\n\n"
    msg += "🌐 <b>GLOBAL BREAKING NEWS & SENTIMENT:</b>\n"
    if news_items:
        for item in news_items:
            msg += f"• {item['sentiment']}: <a href=\"{item['link']}\">{item['title']}</a>\n\n"
    else:
        msg += "• ℹ️ Global news cues stable.\n"

    vix_pct = macros.get("India VIX", {}).get("change_pct", 0)
    if vix_pct > 3.0:
        bias = "⚠️ High Volatility / Bearish Pressure Expected (VIX Spiked)"
    else:
        bias = "🚀 Check 9:10 AM Specific Stock Radar Before Trading!"

    msg += f"\n🎯 <b>PRE-MARKET BIAS:</b>\n<i>{bias}</i>\n"
    msg += "═════════════════════════\n"
    msg += "🤖 <i>Shambhu's Live Precision Radar Engine</i>"

    send_telegram_alert(msg)

def send_910_am_table_report():
    now_ist = datetime.now(IST)
    headers = {"User-Agent": "Mozilla/5.0"}
    news_24h = []

    nifty_p = get_accurate_price("^NSEI")
    bank_p = get_accurate_price("^NSEBANK")
    sensex_p = get_accurate_price("^BSESN")
    vix_p = get_accurate_price("^INDIAVIX")

    msg = f"📊 <b>09:10 AM INDIAN MARKET & STOCKS RADAR</b> 📊\n"
    msg += f"📅 <i>{now_ist.strftime('%d-%b-%Y')}</i>\n"
    msg += "═════════════════════════\n\n"

    msg += "🇮🇳 <b>INDIAN MARKET SNAPSHOT:</b>\n"
    msg += f"• <b>NIFTY 50:</b> ₹{nifty_p:,.2f}\n"
    msg += f"• <b>BANK NIFTY:</b> ₹{bank_p:,.2f}\n"
    msg += f"• <b>SENSEX:</b> ₹{sensex_p:,.2f}\n"
    msg += f"• <b>INDIA VIX:</b> {vix_p:.2f}\n"
    msg += "\n-----------------------------------------\n\n"

    msg += "🏗️ <b>NIFTY 50 WEIGHTAGE STOCKS MOOD:</b>\n"
    for w_name, w_sym in NIFTY_WEIGHTAGE_STOCKS.items():
        p = get_accurate_price(w_sym)
        msg += f"• {w_name}: ₹{p:,.2f}\n"

    msg += "\n-----------------------------------------\n\n"

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
                    link = item.link.text.strip() if item.link else ""
                    pub_date_str = item.pubDate.text.strip() if item.pubDate else ""

                    pub_dt = parse_exact_pub_date(pub_date_str)
                    is_within_24h = (now_ist - pub_dt) <= timedelta(hours=24)

                    if is_within_24h and title:
                        display_name, yf_symbol = extract_single_stock_only(title)
                        if display_name and yf_symbol:
                            sent, _ = analyze_sentiment(title)
                            if "NEUTRAL" not in sent:
                                news_24h.append({"stock": display_name, "sentiment": sent, "title": title, "link": link})
                                news_watched_stocks.add((display_name, yf_symbol))
        except Exception:
            pass

    unique_table = {}
    for item in news_24h:
        unique_table[item["stock"]] = item

    msg += "📰 <b>24-HOUR SPECIFIC STOCK RADAR:</b>\n"
    if unique_table:
        for st, item in unique_table.items():
            if item.get('link'):
                msg += f"• <b>#{st}:</b> <a href=\"{item['link']}\">{item['title']}</a> ({item['sentiment']})\n\n"
            else:
                msg += f"• <b>#{st}:</b> {item['title']} ({item['sentiment']})\n\n"
        
        msg += f"🔍 <i>Total {len(unique_table)} specific stocks active on 3-Min Radar!</i>\n"
    else:
        msg += "ℹ️ <i>No specific stock news detected in the last 24 hours.</i>\n"

    msg += "═════════════════════════\n"
    msg += "🤖 <i>Shambhu's Live Precision Radar Engine</i>"

    send_telegram_alert(msg)

def send_330_pm_closing_summary():
    now_ist = datetime.now(IST)

    win_rate_summary = get_win_rate_summary_text()

    msg = f"📊 <b>03:30 PM MARKET CLOSING SUMMARY REPORT</b> 📊\n"
    msg += f"📅 <i>{now_ist.strftime('%d-%b-%Y')}</i>\n"
    msg += "═════════════════════════\n\n"

    msg += "📈 <b>INDICES CLOSING PRICES:</b>\n"
    for idx_sym, idx_name in INDICES_MAP.items():
        msg += f"• <b>{idx_name}:</b> ₹{get_accurate_price(idx_sym):,.2f}\n"
    msg += "\n-----------------------------------------\n\n"

    msg += f"{win_rate_summary}"
    msg += "\n-----------------------------------------\n\n"

    msg += f"📰 <b>TODAY'S SPECIFIC STOCK NEWS ({len(day_news_log)}):</b>\n"
    if day_news_log:
        for item in day_news_log[-8:]:
            dots = item.get('dots', '')
            msg += f"• <b>#{item['stock']}</b> ({item['time']}) | {dots} {item['sentiment']}\n"
            if item.get('link'):
                msg += f"  └ 📰 <a href=\"{item['link']}\">{item['title']}</a>\n"
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

    # दिवस संपल्यावर रिसेट करणे
    day_news_log.clear()
    day_plus_signals_log.clear()
    stock_news_tracker.clear()
    TRADE_STATS["total_signals"] = 0
    TRADE_STATS["target_hit"] = 0
    TRADE_STATS["sl_hit"] = 0
    ACTIVE_MONITORED_TRADES.clear()

# Helper for parallel execution
def _scan_single_item(item):
    sym, name, is_idx = item
    sig = check_3min_plus_signal(sym, name, is_index=is_idx)
    if sig:
        send_instant_plus_signal_alert(sig)

# ==================== MAIN RADAR ENGINE ====================
def scan_and_alert():
    global last_sent_845_date, last_sent_910_date, last_sent_330_date

    now_ist = datetime.now(IST)
    current_time = now_ist.strftime("%H:%M")
    today_date = now_ist.strftime("%Y-%m-%d")

    # १. वेळेवर आधारित डेली रिपोर्ट्स
    if current_time == "08:45" and last_sent_845_date != today_date:
        send_845_am_premarket_report()
        last_sent_845_date = today_date

    if current_time == "09:10" and last_sent_910_date != today_date:
        send_910_am_table_report()
        last_sent_910_date = today_date

    if current_time == "15:30" and last_sent_330_date != today_date:
        send_330_pm_closing_summary()
        last_sent_330_date = today_date

    # २. लाईव्ह बातम्या फेच करणे
    fetch_and_collect_stock_news()

    # ३. ओपन ट्रेड्सचे Target & SL चेक करणे
    update_and_check_trade_outcomes()

    # 🎯 ⚡ PARALLEL SCANNING (सुपरफास्ट स्पीडसाठी ThreadPoolExecutor)
    if is_market_hours():
        scan_items = []
        
        # A. इंडायसेस
        for index_sym, index_name in INDICES_MAP.items():
            scan_items.append((index_sym, index_name, True))

        # B. बातम्या आलेले स्टॉक्स
        for s_name, s_sym in list(news_watched_stocks):
            scan_items.append((s_sym, s_name, False))

        # C. Nifty 50 Weightage स्टॉक्स
        for w_name, w_sym in NIFTY_WEIGHTAGE_STOCKS.items():
            scan_items.append((w_sym, w_name, False))

        # समांतर पद्धतीने (Parallel) एकाच वेळी सर्व स्कॅन करणे
        with ThreadPoolExecutor(max_workers=10) as executor:
            executor.map(_scan_single_item, scan_items)

if __name__ == "__main__":
    print("🚀 Starting Shambhu's Radar Engine...")

    t = threading.Thread(target=run_server)
    t.daemon = True
    t.start()

    send_telegram_alert("🚀 <b>Radar Engine Active & Updated with Superfast Speed & Interactive Buttons!</b>")

    while True:
        try:
            time.sleep(CHECK_INTERVAL)
            scan_and_alert()
        except Exception as e:
            print(f"Main Loop Error: {e}")
            time.sleep(10)
