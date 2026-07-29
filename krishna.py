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
from functools import wraps
from collections import defaultdict
from dataclasses import dataclass, asdict
from typing import Optional, Dict, List, Tuple, Set, Any
import signal

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

# ==================== LOGGING SETUP ====================
def setup_logging():
    """Setup proper logging with file and console handlers"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler('radar_engine.log', encoding='utf-8'),
            logging.StreamHandler()
        ]
    )
    return logging.getLogger(__name__)

logger = setup_logging()

# Suppress warnings
warnings.simplefilter(action="ignore", category=FutureWarning)
warnings.filterwarnings("ignore")
logging.getLogger("yfinance").setLevel(logging.CRITICAL)
logging.getLogger("matplotlib").setLevel(logging.WARNING)

# ==================== CONFIGURATION CLASS ====================
class Config:
    """Centralized configuration management"""
    def __init__(self):
        # Telegram Configuration
        self.TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8634800722:AAESXRx8Xx3i1mqQvJCsh8ecLd0eP3kPdJQ")
        self.TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "1106122116")
        
        # Timing Configuration
        self.CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", 15))
        self.MARKET_OPEN = "09:15"
        self.MARKET_CLOSE = "15:30"
        self.IST = timezone(timedelta(hours=5, minutes=30))
        
        # Risk Management
        self.MAX_RISK_PER_TRADE = int(os.getenv("MAX_RISK_PER_TRADE", 1000))
        
        # News Configuration
        self.NEWS_COOLDOWN_SECONDS = int(os.getenv("NEWS_COOLDOWN_SECONDS", 300))
        self.STOCK_NEWS_AGE_LIMIT = 3600  # 1 hour
        self.MACRO_NEWS_AGE_LIMIT = 1800   # 30 minutes
        
        # Performance
        self.MAX_WORKERS = int(os.getenv("MAX_WORKERS", 10))
        self.CACHE_TTL = int(os.getenv("CACHE_TTL", 5))
        
        # Formatting
        self.TIME_FORMAT = "%I:%M:%S %p"
        self.DATE_FORMAT = "%d-%b-%Y"
        self.DATETIME_FORMAT = "%d-%b-%Y | %I:%M:%S %p"
        
        # HTTP Headers
        self.HTTP_HEADERS = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        }

config = Config()
IST = config.IST

# ==================== DATA CLASSES ====================
@dataclass
class SignalData:
    """Structure for signal data"""
    name: str
    symbol: str
    direction: str
    sentiment: str
    action: str
    price: float
    sl: float
    target: float
    rsi: float
    strike: str
    warning_note: str
    vol_ratio: str
    time: str
    vwap_info: str
    supertrend_info: str
    risk_per_share: float
    recommended_qty: int

@dataclass
class NewsData:
    """Structure for news data"""
    stock: str
    symbol: str
    price: float
    title: str
    sentiment: str
    time: str
    link: str
    marks: str

@dataclass
class TradeData:
    """Structure for active trades"""
    symbol: str
    direction: str
    target: float
    sl: float
    entry_time: datetime
    entry_price: float

# ==================== CACHE SYSTEM ====================
class PriceCache:
    """Cache for price data with TTL"""
    def __init__(self, ttl: int = 5):
        self.cache: Dict[str, Tuple[float, float]] = {}
        self.ttl = ttl
        
    def get(self, symbol: str) -> Optional[float]:
        """Get cached price if valid"""
        if symbol in self.cache:
            price, timestamp = self.cache[symbol]
            if time.time() - timestamp < self.ttl:
                return price
        return None
        
    def set(self, symbol: str, price: float):
        """Cache price with timestamp"""
        self.cache[symbol] = (price, time.time())
        
    def clear(self):
        """Clear all cache"""
        self.cache.clear()

price_cache = PriceCache(ttl=config.CACHE_TTL)

# ==================== PERFORMANCE MONITOR ====================
class PerformanceMonitor:
    """Monitor system performance metrics"""
    def __init__(self):
        self.metrics = {
            'scans': 0,
            'signals_detected': 0,
            'news_processed': 0,
            'macro_news_processed': 0,
            'api_errors': 0,
            'avg_scan_time': 0,
            'cache_hits': 0,
            'cache_misses': 0
        }
        self.scan_times: List[float] = []
        self.start_time = time.time()
        
    def record_scan(self, duration: float):
        """Record scan duration"""
        self.metrics['scans'] += 1
        self.scan_times.append(duration)
        if len(self.scan_times) > 100:
            self.scan_times = self.scan_times[-100:]
        self.metrics['avg_scan_time'] = sum(self.scan_times) / len(self.scan_times)
        
    def record_signal(self):
        """Record signal detection"""
        self.metrics['signals_detected'] += 1
        
    def record_news(self):
        """Record news processed"""
        self.metrics['news_processed'] += 1
        
    def record_macro_news(self):
        """Record macro news processed"""
        self.metrics['macro_news_processed'] += 1
        
    def record_api_error(self):
        """Record API error"""
        self.metrics['api_errors'] += 1
        
    def record_cache_hit(self):
        """Record cache hit"""
        self.metrics['cache_hits'] += 1
        
    def record_cache_miss(self):
        """Record cache miss"""
        self.metrics['cache_misses'] += 1
        
    def get_uptime(self) -> str:
        """Get system uptime"""
        uptime_seconds = int(time.time() - self.start_time)
        hours = uptime_seconds // 3600
        minutes = (uptime_seconds % 3600) // 60
        seconds = uptime_seconds % 60
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        
    def get_status_report(self) -> str:
        """Get complete status report"""
        cache_hit_rate = (self.metrics['cache_hits'] / (self.metrics['cache_hits'] + self.metrics['cache_misses']) * 100) if (self.metrics['cache_hits'] + self.metrics['cache_misses']) > 0 else 0
        
        return f"""
📊 <b>SYSTEM PERFORMANCE STATUS</b>
═════════════════════════
• Uptime: <b>{self.get_uptime()}</b>
• Total Scans: <b>{self.metrics['scans']}</b>
• Signals Detected: <b>{self.metrics['signals_detected']}</b>
• News Processed: <b>{self.metrics['news_processed']}</b>
• Macro News: <b>{self.metrics['macro_news_processed']}</b>
• API Errors: <b>{self.metrics['api_errors']}</b>
• Avg Scan Time: <b>{self.metrics['avg_scan_time']:.2f}s</b>
• Cache Hit Rate: <b>{cache_hit_rate:.1f}%</b>
═════════════════════════
"""

monitor = PerformanceMonitor()

# ==================== SUPPRESS STDOUT ====================
class SuppressStdout:
    """Suppress stdout/stderr for specific operations"""
    def __enter__(self):
        self._original_stdout = sys.stdout
        self._original_stderr = sys.stderr
        sys.stdout = io.StringIO()
        sys.stderr = io.StringIO()

    def __exit__(self, exc_type, exc_val, exc_tb):
        sys.stdout = self._original_stdout
        sys.stderr = self._original_stderr

# ==================== RETRY DECORATOR ====================
def retry_on_failure(max_retries: int = 3, delay: float = 1, backoff: float = 2):
    """Retry decorator with exponential backoff"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if attempt == max_retries - 1:
                        logger.error(f"Function {func.__name__} failed after {max_retries} attempts: {e}")
                        raise
                    wait_time = delay * (backoff ** attempt)
                    logger.warning(f"Retry {attempt + 1}/{max_retries} for {func.__name__} in {wait_time:.1f}s")
                    time.sleep(wait_time)
            return None
        return wrapper
    return decorator

# ==================== RATE LIMITER ====================
class RateLimiter:
    """Rate limiter for API calls"""
    def __init__(self, max_calls: int = 10, period: int = 60):
        self.calls: Dict[str, List[float]] = defaultdict(list)
        self.max_calls = max_calls
        self.period = period
        
    def __call__(self, func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            key = func.__name__
            now = time.time()
            # Clean old calls
            self.calls[key] = [t for t in self.calls[key] if now - t < self.period]
            if len(self.calls[key]) >= self.max_calls:
                logger.warning(f"Rate limit exceeded for {key}")
                time.sleep(1)
            self.calls[key].append(now)
            return func(*args, **kwargs)
        return wrapper

rate_limiter = RateLimiter(max_calls=20, period=60)

# ==================== THREAD POOL MANAGER ====================
class ThreadPoolManager:
    """Manage thread pool for scanning"""
    def __init__(self, max_workers: int = 10):
        self.max_workers = max_workers
        self.executor = None
        
    def get_executor(self):
        """Get or create thread pool executor"""
        if self.executor is None:
            self.executor = ThreadPoolExecutor(max_workers=self.max_workers)
        return self.executor
        
    def shutdown(self):
        """Shutdown thread pool"""
        if self.executor:
            self.executor.shutdown(wait=False)
            self.executor = None

pool_manager = ThreadPoolManager(max_workers=config.MAX_WORKERS)

# ==================== CONFIGURATION (Existing) ====================
# Keep all your existing configurations here
# INDICES_MAP, CORE_STOCKS_MAP, MACRO_TICKERS, STOCKS_MAP, etc.
# ... (I'll keep them as is to maintain logic)

INDICES_MAP = {
    "^NSEI": "NIFTY 50",
    "^NSEBANK": "BANK NIFTY",
    "^BSESN": "SENSEX",
}

CORE_STOCKS_MAP = {
    "RELIANCE": "RELIANCE.NS",
    "HDFC BANK": "HDFCBANK.NS",
    "INFOSYS": "INFY.NS",
    "TATA MOTORS": "TATAMOTORS.NS",
    "BAJAJ FINANCE": "BAJFINANCE.NS",
    "L&T": "LT.NS"
}

MACRO_TICKERS = {
    "GIFT Nifty": "^NSEI",
    "US Dow Futures": "YM=F",
    "US Nasdaq Futures": "NQ=F",
    "India VIX": "^INDIAVIX",
    "Crude Oil (WTI)": "CL=F",
    "US Dollar Index (DXY)": "DX-Y.NYB"
}

# ... (rest of your STOCKS_MAP, INDIAN_NEWS_FEEDS, GLOBAL_NEWS_FEEDS, MACRO_KEYWORDS)

# ==================== IMPROVED FUNCTIONS ====================

@retry_on_failure(max_retries=2, delay=1)
def get_accurate_price_improved(symbol: str) -> float:
    """Get accurate price with caching and retry"""
    # Check cache first
    cached_price = price_cache.get(symbol)
    if cached_price:
        monitor.record_cache_hit()
        return cached_price
    
    monitor.record_cache_miss()
    
    with SuppressStdout():
        try:
            t = yf.Ticker(symbol)
            price = getattr(t.fast_info, "last_price", None)
            if price and not pd.isna(price) and price > 0:
                price = float(price)
                price_cache.set(symbol, price)
                return price
            df = t.history(period="1d", interval="1m")
            if not df.empty:
                price = float(df["Close"].iloc[-1])
                price_cache.set(symbol, price)
                return price
        except Exception as e:
            logger.debug(f"Price fetch error for {symbol}: {e}")
            monitor.record_api_error()
    return 0.0

# Keep original function for backward compatibility
def get_accurate_price(symbol: str) -> float:
    """Wrapper for get_accurate_price_improved"""
    return get_accurate_price_improved(symbol)

# ==================== IMPROVED NEWS FUNCTIONS ====================

def process_rss_items(soup, max_items: int = 20, age_limit: int = 3600, is_macro: bool = False) -> List[Dict]:
    """Process RSS items with better error handling"""
    items = soup.find_all("item")
    if not items:
        soup = BeautifulSoup(str(soup), "html.parser")
        items = soup.find_all("item")
    
    processed_items = []
    now_ist = datetime.now(IST)
    
    for item in items[:max_items]:
        try:
            title = item.title.text.strip() if item.title else ""
            link = item.link.text.strip() if item.link else ""
            pub_date_raw = item.pubDate.text.strip() if item.pubDate else ""
            
            if not title:
                continue
                
            pub_time = parse_exact_pub_date(pub_date_raw)
            
            # Check age limit
            if (now_ist - pub_time).total_seconds() > age_limit:
                continue
                
            processed_items.append({
                'title': title,
                'link': link,
                'pub_time': pub_time,
                'pub_time_str': pub_time.strftime(config.TIME_FORMAT)
            })
        except Exception as e:
            logger.debug(f"Error processing RSS item: {e}")
            continue
            
    return processed_items

def check_macro_and_global_news_improved():
    """Improved macro news checking with better filtering"""
    global seen_macro_news_titles
    all_feeds = INDIAN_NEWS_FEEDS + GLOBAL_NEWS_FEEDS
    now_ist = datetime.now(IST)
    batch_news_items = []
    
    for rss_url in all_feeds:
        try:
            resp = requests.get(rss_url, headers=config.HTTP_HEADERS, timeout=6)
            if resp.status_code != 200:
                continue
                
            soup = BeautifulSoup(resp.content, "xml")
            items = process_rss_items(soup, max_items=15, age_limit=config.MACRO_NEWS_AGE_LIMIT, is_macro=True)
            
            for item in items:
                title = item['title']
                link = item['link']
                
                norm_title = normalize_text(title)
                if norm_title in seen_macro_news_titles:
                    continue
                
                title_lower = title.lower()
                matched_kw = None
                for kw in MACRO_KEYWORDS:
                    pattern = r"(?<![a-zA-Z0-9])" + re.escape(kw) + r"(?![a-zA-Z0-9])"
                    if re.search(pattern, title_lower):
                        matched_kw = kw
                        break
                
                if matched_kw:
                    seen_macro_news_titles.add(norm_title)
                    sentiment, _ = analyze_sentiment(title)
                    
                    if "NEUTRAL" in sentiment:
                        continue
                    
                    batch_news_items.append({
                        "keyword": matched_kw.upper(),
                        "sentiment": sentiment,
                        "title": title,
                        "link": link
                    })
                    monitor.record_macro_news()
                    
        except Exception as e:
            logger.error(f"Error in macro news check: {e}")
            monitor.record_api_error()
    
    if batch_news_items:
        send_macro_news_batch_alert(batch_news_items, now_ist)

def send_macro_news_batch_alert(batch_news_items: List[Dict], now_ist: datetime):
    """Send batched macro news alerts"""
    msg = (
        f"🚨 <b>[24*7 MACRO & GLOBAL NEWS ALERT]</b> 🚨\n"
        f"📅 <i>{now_ist.strftime(config.DATETIME_FORMAT)}</i>\n"
        f"═════════════════════════\n\n"
    )
    for idx, n_item in enumerate(batch_news_items, 1):
        msg += (
            f"<b>{idx}. Keyword:</b> <code>{n_item['keyword']}</code> | {n_item['sentiment']}\n"
            f"📰 <a href=\"{n_item['link']}\">{n_item['title'][:150]}{'...' if len(n_item['title']) > 150 else ''}</a>\n\n"
        )
    msg += (
        f"═════════════════════════\n"
        f"🤖 <i>Shambhu's Live Precision Radar Engine</i>"
    )
    send_telegram_alert(msg)

# ==================== IMPROVED SIGNAL FUNCTIONS ====================

def calculate_risk_management(current_price: float, direction: str, atr: float) -> Tuple[float, float, float, int]:
    """Calculate SL, Target, Risk and Quantity"""
    if direction == "BULLISH":
        stop_loss = current_price - (atr * 1.5)
        target = current_price + ((current_price - stop_loss) * 1.5)
    else:
        stop_loss = current_price + (atr * 1.5)
        target = current_price - ((stop_loss - current_price) * 1.5)
    
    risk_per_share = abs(current_price - stop_loss)
    recommended_qty = int(config.MAX_RISK_PER_TRADE / risk_per_share) if risk_per_share > 0 else 1
    
    return stop_loss, target, risk_per_share, recommended_qty

def check_3min_plus_signal_improved(symbol: str, display_name: str, is_index: bool = False) -> Optional[SignalData]:
    """Improved signal detection with better performance"""
    global last_signal_state, last_alert_candle_time
    
    with SuppressStdout():
        try:
            # Get data with caching
            current_close = get_accurate_price(symbol)
            if current_close == 0.0:
                return None
                
            if not is_index and current_close < 200:
                return None
            
            ticker = yf.Ticker(symbol)
            df = ticker.history(period="1d", interval="3m")
            if df.empty or len(df) < 5:
                return None
            
            # Convert to float
            df["Close"] = df["Close"].values.flatten().astype(float)
            df["High"] = df["High"].values.flatten().astype(float)
            df["Low"] = df["Low"].values.flatten().astype(float)
            df["Volume"] = df["Volume"].values.flatten().astype(float)
            
            # Calculate indicators
            df["EMA_9"] = EMAIndicator(close=df["Close"], window=9).ema_indicator()
            df["EMA_26"] = EMAIndicator(close=df["Close"], window=26).ema_indicator()
            df["ATR_14"] = AverageTrueRange(high=df["High"], low=df["Low"], close=df["Close"], window=14).average_true_range()
            df["RSI_14"] = RSIIndicator(close=df["Close"], window=14).rsi()
            df["Vol_SMA"] = df["Volume"].rolling(window=20).mean()
            
            # Calculate VWAP
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
            
            atr_val = float(row_now["ATR_14"]) if not pd.isna(row_now["ATR_14"]) else current_close * 0.005
            rsi_val = float(row_now["RSI_14"]) if not pd.isna(row_now["RSI_14"]) else 50.0
            current_vol = float(row_now["Volume"])
            vol_sma = float(row_now["Vol_SMA"]) if not pd.isna(row_now["Vol_SMA"]) else 0.0
            
            vol_ratio = (current_vol / vol_sma) if vol_sma > 0 else 1.0
            
            # Volume warning
            warning_note = ""
            if vol_ratio < 1.0 and not is_index:
                warning_note = "⚠️ Volume is low (<1.0x SMA)"
            elif vol_ratio >= 2.0 and not is_index:
                warning_note = "🔥 High Volume Confirmation (>2.0x SMA)"
            else:
                warning_note = "✅ Volume Normal"
            
            # Check crossover
            now_ema9 = float(row_now["EMA_9"])
            now_ema26 = float(row_now["EMA_26"])
            prev_ema9 = float(row_prev["EMA_9"])
            prev_ema26 = float(row_prev["EMA_26"])
            
            fresh_bullish = (prev_ema9 <= prev_ema26) and (now_ema9 > now_ema26)
            fresh_bearish = (prev_ema9 >= prev_ema26) and (now_ema9 < now_ema26)
            
            if fresh_bullish:
                current_direction = "BULLISH"
            elif fresh_bearish:
                current_direction = "BEARISH"
            else:
                current_direction = "NONE"
            
            with signal_lock:
                if current_direction != "NONE":
                    if last_alert_candle_time.get(symbol) == candle_timestamp:
                        return None
                    
                    last_signal_state[symbol] = current_direction
                    last_alert_candle_time[symbol] = candle_timestamp
                    
                    action = "BUY / CALL (CE)" if current_direction == "BULLISH" else "BUY / PUT (PE)"
                    opt_type = "CE" if current_direction == "BULLISH" else "PE"
                    
                    # Calculate risk management
                    stop_loss, target, risk_per_share, recommended_qty = calculate_risk_management(
                        current_close, current_direction, atr_val
                    )
                    
                    suggested_strike = calculate_strike_price(display_name, current_close, opt_type) if is_index else "N/A"
                    
                    signal_data = SignalData(
                        name=display_name,
                        symbol=symbol,
                        direction=current_direction,
                        sentiment=f"{'🟢' if current_direction == 'BULLISH' else '🔴'} {current_direction} PLUS (+) SIGN",
                        action=action,
                        price=current_close,
                        sl=stop_loss,
                        target=target,
                        rsi=rsi_val,
                        strike=suggested_strike,
                        warning_note=warning_note,
                        vol_ratio=f"{vol_ratio:.1f}x",
                        time=datetime.now(IST).strftime(config.TIME_FORMAT),
                        vwap_info=vwap_info,
                        supertrend_info=supertrend_info,
                        risk_per_share=risk_per_share,
                        recommended_qty=recommended_qty
                    )
                    
                    # Convert to dict for existing code
                    sig_dict = asdict(signal_data)
                    
                    day_plus_signals_log.append(sig_dict)
                    TRADE_STATS["total_signals"] += 1
                    ACTIVE_MONITORED_TRADES.append({
                        "symbol": symbol,
                        "direction": current_direction,
                        "target": target,
                        "sl": stop_loss,
                        "entry_time": datetime.now(IST),
                        "entry_price": current_close
                    })
                    
                    monitor.record_signal()
                    return signal_data
                    
        except Exception as e:
            logger.error(f"Signal check error for {symbol}: {e}")
            monitor.record_api_error()
    
    return None

# ==================== IMPROVED MAIN SCAN FUNCTION ====================

def scan_and_alert_improved():
    """Improved main scan function with performance monitoring"""
    global last_sent_845_date, last_sent_910_date, last_sent_330_date
    
    scan_start = time.time()
    
    try:
        now_ist = datetime.now(IST)
        current_time = now_ist.strftime("%H:%M")
        today_date = now_ist.strftime("%Y-%m-%d")
        
        # Scheduled reports
        if current_time == "08:45" and last_sent_845_date != today_date:
            send_845_am_premarket_report()
            last_sent_845_date = today_date
            logger.info("Sent 8:45 AM pre-market report")
        
        if current_time == "09:10" and last_sent_910_date != today_date:
            send_910_am_table_report()
            last_sent_910_date = today_date
            logger.info("Sent 9:10 AM market snapshot")
        
        if current_time == "15:30" and last_sent_330_date != today_date:
            send_330_pm_closing_summary()
            last_sent_330_date = today_date
            logger.info("Sent 3:30 PM closing summary")
        
        # Check news
        check_macro_and_global_news_improved()
        fetch_and_collect_stock_news()
        update_and_check_trade_outcomes()
        
        # Scan signals during market hours
        if is_market_hours():
            scan_dict = {}
            
            # Add indices
            for index_sym, index_name in INDICES_MAP.items():
                scan_dict[index_sym] = (index_sym, index_name, True)
            
            # Add core stocks
            for s_name, s_sym in CORE_STOCKS_MAP.items():
                scan_dict[s_sym] = (s_sym, s_name, False)
            
            # Add news-watched stocks
            for s_name, s_sym in list(news_watched_stocks):
                if s_sym not in scan_dict:
                    scan_dict[s_sym] = (s_sym, s_name, False)
            
            scan_items = list(scan_dict.values())
            
            # Use thread pool
            executor = pool_manager.get_executor()
            futures = []
            for item in scan_items:
                future = executor.submit(_scan_single_item_improved, item)
                futures.append(future)
            
            # Wait for all to complete (with timeout)
            for future in futures:
                try:
                    future.result(timeout=2)
                except Exception as e:
                    logger.debug(f"Scan item error: {e}")
                    
    except Exception as e:
        logger.error(f"Scan error: {e}")
        monitor.record_api_error()
    
    # Record performance
    scan_duration = time.time() - scan_start
    monitor.record_scan(scan_duration)
    
    # Log performance periodically
    if monitor.metrics['scans'] % 10 == 0:
        logger.info(f"Performance: {monitor.get_status_report()}")

def _scan_single_item_improved(item):
    """Improved single item scanner"""
    sym, name, is_idx = item
    try:
        sig = check_3min_plus_signal_improved(sym, name, is_index=is_idx)
        if sig:
            send_instant_plus_signal_alert(asdict(sig))
    except Exception as e:
        logger.error(f"Error scanning {name}: {e}")

# ==================== GRACEFUL SHUTDOWN ====================

def signal_handler(sig, frame):
    """Handle shutdown signals gracefully"""
    logger.info("🛑 Received shutdown signal. Cleaning up...")
    try:
        send_telegram_alert("🛑 Radar Engine shutting down gracefully")
    except:
        pass
    pool_manager.shutdown()
    logger.info("Cleanup complete. Exiting...")
    sys.exit(0)

# Register signal handlers
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

# ==================== HEALTH CHECK ====================

def check_internet_connection() -> bool:
    """Check if internet is available"""
    try:
        requests.get("https://www.google.com", timeout=5)
        return True
    except:
        return False

def run_health_check():
    """Run periodic health checks"""
    while True:
        try:
            if not check_internet_connection():
                logger.warning("No internet connection detected")
                send_telegram_alert("⚠️ No internet connection detected!")
            
            # Send periodic status
            if monitor.metrics['scans'] % 100 == 0 and monitor.metrics['scans'] > 0:
                status_msg = monitor.get_status_report()
                send_telegram_alert(status_msg)
                
        except Exception as e:
            logger.error(f"Health check error: {e}")
        
        time.sleep(3600)  # Every hour

# ==================== FLASK SERVER ====================

flask_app = Flask("")

@flask_app.route("/")
def home():
    return f"""
    ⚡ Shambhu's Live Radar Engine Active! ⚡<br><br>
    {monitor.get_status_report().replace('\n', '<br>')}
    """

@flask_app.route("/status")
def status():
    return monitor.get_status_report()

@flask_app.route("/metrics")
def metrics():
    return json.dumps(monitor.metrics)

def run_server():
    port = int(os.environ.get("PORT", 8080))
    flask_app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

# ==================== MAIN EXECUTION ====================

if __name__ == "__main__":
    logger.info("🚀 Starting Shambhu's Radar Engine...")
    
    # Start Flask server in background
    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()
    
    # Start health check in background
    health_thread = threading.Thread(target=run_health_check, daemon=True)
    health_thread.start()
    
    # Send startup alert
    try:
        send_telegram_alert("🚀 <b>Radar Engine Active!</b>\n\n📊 EMA Crossover & 24*7 Macro News Alerts Enabled\n⚡ Performance Monitoring Active\n🛡️ Auto-Restart Enabled")
    except Exception as e:
        logger.error(f"Startup alert error: {e}")
    
    # Main loop
    while True:
        try:
            time.sleep(config.CHECK_INTERVAL)
            scan_and_alert_improved()
        except KeyboardInterrupt:
            logger.info("Received keyboard interrupt, shutting down...")
            break
        except Exception as e:
            logger.critical(f"Main Loop Critical Error: {e}")
            try:
                send_telegram_alert(f"⚠️ System Restarting due to critical error: {str(e)[:100]}")
            except:
                pass
            time.sleep(10)
            continue
