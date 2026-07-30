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
from queue import Queue, Empty
import sqlite3
import pyttsx3

from bs4 import BeautifulSoup
from flask import Flask, render_template_string
from flask_socketio import SocketIO, emit
import pandas as pd
import requests
import yfinance as yf

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from ta.momentum import RSIIndicator
from ta.trend import EMAIndicator
from ta.volatility import AverageTrueRange

# ==================== OPENAI (Optional) ====================
try:
    import openai
    openai.api_key = os.getenv("OPENAI_API_KEY")
    OPENAI_AVAILABLE = bool(openai.api_key)
except:
    OPENAI_AVAILABLE = False

# ==================== LOGGING SETUP ====================
def setup_logging():
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

warnings.simplefilter(action="ignore", category=FutureWarning)
warnings.filterwarnings("ignore")
logging.getLogger("yfinance").setLevel(logging.CRITICAL)
logging.getLogger("matplotlib").setLevel(logging.WARNING)

# ==================== CONFIGURATION CLASS ====================
class Config:
    def __init__(self):
        self.TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8634800722:AAESXRx8Xx3i1mqQvJCsh8ecLd0eP3kPdJQ")
        self.TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "1106122116")
        self.CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", 15))
        self.MARKET_OPEN = "09:15"
        self.MARKET_CLOSE = "15:30"
        self.IST = timezone(timedelta(hours=5, minutes=30))
        self.MAX_RISK_PER_TRADE = int(os.getenv("MAX_RISK_PER_TRADE", 1000))
        self.NEWS_COOLDOWN_SECONDS = int(os.getenv("NEWS_COOLDOWN_SECONDS", 300))
        self.STOCK_NEWS_AGE_LIMIT = 3600
        self.MACRO_NEWS_AGE_LIMIT = 1800
        self.MAX_WORKERS = int(os.getenv("MAX_WORKERS", 10))
        self.CACHE_TTL = int(os.getenv("CACHE_TTL", 5))
        self.BATCH_INTERVAL = 60
        self.HIGH_PRIORITY_STOCKS = ["RELIANCE.NS", "HDFCBANK.NS", "INFY.NS", "TATAMOTORS.NS", "BAJFINANCE.NS"]
        self.MEDIUM_PRIORITY_STOCKS = ["ICICIBANK.NS", "KOTAKBANK.NS", "SBIN.NS", "LT.NS"]
        self.HIGH_PRIORITY_INTERVAL = 8
        self.MEDIUM_PRIORITY_INTERVAL = 15
        self.LOW_PRIORITY_INTERVAL = 30
        self.TIME_FORMAT = "%I:%M:%S %p"
        self.DATE_FORMAT = "%d-%b-%Y"
        self.DATETIME_FORMAT = "%d-%b-%Y | %I:%M:%S %p"
        self.HTTP_HEADERS = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        }

config = Config()
IST = config.IST

# ==================== DATA CLASSES ====================
@dataclass
class SignalData:
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
    confidence: int = 0
    momentum_score: int = 0

@dataclass
class NewsData:
    stock: str
    symbol: str
    price: float
    title: str
    sentiment: str
    time: str
    link: str
    marks: str
    quality_score: int = 0

@dataclass
class TradeData:
    symbol: str
    direction: str
    target: float
    sl: float
    entry_time: datetime
    entry_price: float
    exit_time: Optional[datetime] = None
    exit_price: Optional[float] = None
    result: Optional[str] = None

# ==================== SMART CACHE SYSTEM ====================
class SmartCache:
    def __init__(self):
        self.cache: Dict[str, Tuple[float, float]] = {}
        self.priority_ttl = {'high': 10, 'medium': 8, 'low': 5}
        
    def get_priority(self, symbol: str) -> str:
        if symbol in config.HIGH_PRIORITY_STOCKS:
            return 'high'
        elif symbol in config.MEDIUM_PRIORITY_STOCKS:
            return 'medium'
        return 'low'
    
    def get(self, symbol: str) -> Optional[float]:
        if symbol in self.cache:
            price, timestamp = self.cache[symbol]
            ttl = self.priority_ttl[self.get_priority(symbol)]
            if time.time() - timestamp < ttl:
                monitor.record_cache_hit()
                return price
        monitor.record_cache_miss()
        return None
        
    def set(self, symbol: str, price: float):
        self.cache[symbol] = (price, time.time())
        
    def clear(self):
        self.cache.clear()

price_cache = SmartCache()

# ==================== PERFORMANCE MONITOR ====================
class PerformanceMonitor:
    def __init__(self):
        self.metrics = {
            'scans': 0, 'signals_detected': 0, 'news_processed': 0,
            'macro_news_processed': 0, 'api_errors': 0, 'avg_scan_time': 0,
            'cache_hits': 0, 'cache_misses': 0,
            'high_priority_signals': 0, 'medium_priority_signals': 0,
            'low_priority_signals': 0, 'win_rate': 0,
            'total_trades': 0, 'winning_trades': 0
        }
        self.scan_times: List[float] = []
        self.start_time = time.time()
        self.signal_queue = Queue()
        
    def record_scan(self, duration: float):
        self.metrics['scans'] += 1
        self.scan_times.append(duration)
        if len(self.scan_times) > 100:
            self.scan_times = self.scan_times[-100:]
        self.metrics['avg_scan_time'] = sum(self.scan_times) / len(self.scan_times)
        
    def record_signal(self, priority: str = 'low'):
        self.metrics['signals_detected'] += 1
        if priority == 'high':
            self.metrics['high_priority_signals'] += 1
        elif priority == 'medium':
            self.metrics['medium_priority_signals'] += 1
        else:
            self.metrics['low_priority_signals'] += 1
        
    def record_news(self):
        self.metrics['news_processed'] += 1
        
    def record_macro_news(self):
        self.metrics['macro_news_processed'] += 1
        
    def record_api_error(self):
        self.metrics['api_errors'] += 1
        
    def record_cache_hit(self):
        self.metrics['cache_hits'] += 1
        
    def record_cache_miss(self):
        self.metrics['cache_misses'] += 1
        
    def record_trade_result(self, result: str):
        self.metrics['total_trades'] += 1
        if result == 'WIN':
            self.metrics['winning_trades'] += 1
        self.metrics['win_rate'] = (self.metrics['winning_trades'] / self.metrics['total_trades'] * 100) if self.metrics['total_trades'] > 0 else 0
        
    def get_uptime(self) -> str:
        uptime_seconds = int(time.time() - self.start_time)
        hours = uptime_seconds // 3600
        minutes = (uptime_seconds % 3600) // 60
        seconds = uptime_seconds % 60
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    
    def get_cache_hit_rate(self) -> float:
        total = self.metrics['cache_hits'] + self.metrics['cache_misses']
        return (self.metrics['cache_hits'] / total * 100) if total > 0 else 0
        
    def get_status_report(self) -> str:
        return f"""
📊 <b>SYSTEM PERFORMANCE STATUS</b>
═════════════════════════
• Uptime: <b>{self.get_uptime()}</b>
• Total Scans: <b>{self.metrics['scans']}</b>
• Signals Detected: <b>{self.metrics['signals_detected']}</b>
  ├─ High Priority: {self.metrics['high_priority_signals']} 🚀
  ├─ Medium Priority: {self.metrics['medium_priority_signals']} 📈
  └─ Low Priority: {self.metrics['low_priority_signals']} ⚪
• News Processed: <b>{self.metrics['news_processed']}</b>
• Macro News: <b>{self.metrics['macro_news_processed']}</b>
• API Errors: <b>{self.metrics['api_errors']}</b>
• Avg Scan Time: <b>{self.metrics['avg_scan_time']:.2f}s</b>
• Cache Hit Rate: <b>{self.get_cache_hit_rate():.1f}%</b>
• Win Rate: <b>{self.metrics['win_rate']:.1f}%</b>
═════════════════════════
"""

monitor = PerformanceMonitor()

# ==================== DATABASE (SQLite) ====================
class Database:
    def __init__(self, db_file='trading_data.db'):
        self.conn = sqlite3.connect(db_file, check_same_thread=False)
        self.create_tables()
    
    def create_tables(self):
        c = self.conn.cursor()
        c.execute('''
            CREATE TABLE IF NOT EXISTS signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT, symbol TEXT, direction TEXT,
                price REAL, sl REAL, target REAL,
                confidence INTEGER, time TEXT,
                result TEXT, entry_time TEXT
            )
        ''')
        c.execute('''
            CREATE TABLE IF NOT EXISTS news (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                stock TEXT, symbol TEXT, title TEXT,
                sentiment TEXT, time TEXT, link TEXT,
                quality INTEGER
            )
        ''')
        c.execute('''
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT, direction TEXT,
                entry_price REAL, exit_price REAL,
                entry_time TEXT, exit_time TEXT,
                result TEXT
            )
        ''')
        self.conn.commit()
    
    def save_signal(self, signal: Dict):
        c = self.conn.cursor()
        c.execute('''
            INSERT INTO signals (name, symbol, direction, price, sl, target, confidence, time, entry_time)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (signal['name'], signal['symbol'], signal['direction'],
              signal['price'], signal['sl'], signal['target'],
              signal.get('confidence', 0), signal['time'],
              datetime.now(IST).isoformat()))
        self.conn.commit()
    
    def save_news(self, news: Dict):
        c = self.conn.cursor()
        c.execute('''
            INSERT INTO news (stock, symbol, title, sentiment, time, link, quality)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (news['stock'], news['symbol'], news['title'],
              news['sentiment'], news['time'], news.get('link', ''),
              news.get('quality', 0)))
        self.conn.commit()
    
    def save_trade(self, trade: Dict):
        c = self.conn.cursor()
        c.execute('''
            INSERT INTO trades (symbol, direction, entry_price, exit_price, entry_time, exit_time, result)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (trade['symbol'], trade['direction'],
              trade['entry_price'], trade.get('exit_price'),
              trade['entry_time'], trade.get('exit_time'),
              trade.get('result')))
        self.conn.commit()
    
    def get_recent_signals(self, limit=20):
        c = self.conn.cursor()
        c.execute('SELECT * FROM signals ORDER BY id DESC LIMIT ?', (limit,))
        return c.fetchall()
    
    def get_stats(self):
        c = self.conn.cursor()
        c.execute('SELECT COUNT(*) FROM signals')
        total = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM signals WHERE result='WIN'")
        wins = c.fetchone()[0]
        return {'total_signals': total, 'wins': wins}

db = Database()

# ==================== SUPPRESS STDOUT ====================
class SuppressStdout:
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
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if attempt == max_retries - 1:
                        logger.error(f"Function {func.__name__} failed after {max_retries} attempts: {e}")
                        monitor.record_api_error()
                        raise
                    wait_time = delay * (backoff ** attempt)
                    logger.warning(f"Retry {attempt + 1}/{max_retries} for {func.__name__} in {wait_time:.1f}s")
                    time.sleep(wait_time)
            return None
        return wrapper
    return decorator

# ==================== RATE LIMITER ====================
class RateLimiter:
    def __init__(self, max_calls: int = 10, period: int = 60):
        self.calls: Dict[str, List[float]] = defaultdict(list)
        self.max_calls = max_calls
        self.period = period
        
    def __call__(self, func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            key = func.__name__
            now = time.time()
            self.calls[key] = [t for t in self.calls[key] if now - t < self.period]
            if len(self.calls[key]) >= self.max_calls:
                logger.warning(f"Rate limit exceeded for {key}, waiting...")
                time.sleep(2)
            self.calls[key].append(now)
            return func(*args, **kwargs)
        return wrapper

rate_limiter = RateLimiter(max_calls=20, period=60)

# ==================== THREAD POOL MANAGER ====================
class ThreadPoolManager:
    def __init__(self, max_workers: int = 10):
        self.max_workers = max_workers
        self.executor = None
        
    def get_executor(self):
        if self.executor is None:
            self.executor = ThreadPoolExecutor(max_workers=self.max_workers)
        return self.executor
        
    def shutdown(self):
        if self.executor:
            self.executor.shutdown(wait=False)
            self.executor = None

pool_manager = ThreadPoolManager(max_workers=config.MAX_WORKERS)

# ==================== SMART NEWS FILTER ====================
class SmartNewsFilter:
    def __init__(self):
        self.trusted_sources = {
            'reuters.com': 10,
            'bloomberg.com': 10,
            'moneycontrol.com': 9,
            'economictimes.com': 8,
            'livemint.com': 8,
            'business-standard.com': 7,
            'cnbc.com': 9,
            'investing.com': 7
        }
        self.blacklist_keywords = ['advertisement', 'sponsored', 'promotion', 'click here']
        
    def get_quality_score(self, link: str, title: str) -> int:
        score = 5
        for source, quality in self.trusted_sources.items():
            if source in link.lower():
                score = quality
                break
        for keyword in self.blacklist_keywords:
            if keyword in title.lower():
                score -= 3
        if len(title) > 50:
            score += 2
        if len(title) > 100:
            score += 1
        return max(1, min(10, score))
    
    def should_alert(self, news: Dict) -> bool:
        quality = self.get_quality_score(news.get('link', ''), news.get('title', ''))
        return quality >= 6

news_filter = SmartNewsFilter()

# ==================== SMART SENTIMENT ANALYSIS ====================
class SmartSentimentAnalyzer:
    def __init__(self):
        self.bullish_phrases = [
            "beats estimates", "above expectations", "record high", "all-time high",
            "strong demand", "positive outlook", "outperform", "buy rating",
            "upgrade", "target raised", "strong growth", "robust earnings",
            "dividend", "bonus", "stock split", "surges", "jumps", "soars",
            "bull run", "breakout", "upside", "momentum", "rally",
            "strong earnings", "record", "milestone", "breakthrough"
        ]
        self.bearish_phrases = [
            "misses estimates", "below expectations", "record low", "all-time low",
            "weak demand", "negative outlook", "underperform", "sell rating",
            "downgrade", "target cut", "slow growth", "weak earnings",
            "default", "fraud", "investigation", "plunges", "drops", "crashes",
            "bear market", "collapse", "freefall", "meltdown", "selloff",
            "panic", "bloodbath", "correction", "downtrend", "weakness"
        ]
        self.modifiers = {
            "not": -1, "no": -1, "never": -1,
            "very": 2, "extremely": 2, "slightly": 0.5,
            "significantly": 1.5, "marginally": 0.5
        }
        
    def analyze(self, text: str) -> Tuple[str, int, int]:
        text_lower = text.lower()
        score = 0
        phrase_matches = 0
        
        for phrase in self.bullish_phrases:
            if phrase in text_lower:
                score += 2
                phrase_matches += 1
        
        for phrase in self.bearish_phrases:
            if phrase in text_lower:
                score -= 2
                phrase_matches += 1
        
        words = text_lower.split()
        for i, word in enumerate(words):
            if word in self.modifiers:
                if i + 1 < len(words):
                    next_word = words[i + 1]
                    if any(phrase in next_word for phrase in self.bullish_phrases):
                        score += self.modifiers[word]
                    elif any(phrase in next_word for phrase in self.bearish_phrases):
                        score -= self.modifiers[word]
        
        if score > 2:
            return "🟢 POSITIVE", abs(score), min(100, phrase_matches * 20)
        elif score < -2:
            return "🔴 NEGATIVE", abs(score), min(100, phrase_matches * 20)
        else:
            return "⚪ NEUTRAL", 0, min(100, phrase_matches * 10)

sentiment_analyzer = SmartSentimentAnalyzer()

# ==================== CONFIDENCE & MOMENTUM SCORING ====================
class SignalConfidenceScorer:
    def __init__(self):
        self.history = {}
    
    def calculate_confidence(self, signal: SignalData) -> int:
        confidence = 0
        if 40 <= signal.rsi <= 60:
            confidence += 20
        elif 30 <= signal.rsi <= 70:
            confidence += 10
        vol_ratio = float(signal.vol_ratio.replace('x', ''))
        if vol_ratio >= 2.0:
            confidence += 20
        elif vol_ratio >= 1.5:
            confidence += 15
        elif vol_ratio >= 1.0:
            confidence += 10
        if "Above VWAP" in signal.vwap_info and signal.direction == "BULLISH":
            confidence += 15
        elif "Below VWAP" in signal.vwap_info and signal.direction == "BEARISH":
            confidence += 15
        elif "Above VWAP" in signal.vwap_info and signal.direction == "BEARISH":
            confidence += 5
        elif "Below VWAP" in signal.vwap_info and signal.direction == "BULLISH":
            confidence += 5
        if "Bullish" in signal.supertrend_info and signal.direction == "BULLISH":
            confidence += 15
        elif "Bearish" in signal.supertrend_info and signal.direction == "BEARISH":
            confidence += 15
        else:
            confidence += 5
        matching_news = [n for n in day_news_log if n['symbol'] == signal.symbol]
        if matching_news:
            latest = matching_news[-1]
            if "POSITIVE" in latest['sentiment'] and signal.direction == "BULLISH":
                confidence += 15
            elif "NEGATIVE" in latest['sentiment'] and signal.direction == "BEARISH":
                confidence += 15
            elif "POSITIVE" in latest['sentiment']:
                confidence += 5
            elif "NEGATIVE" in latest['sentiment']:
                confidence += 5
        if signal.symbol in self.history:
            accuracy = self.history[signal.symbol].get('accuracy', 0)
            confidence += (accuracy * 15) / 100
        return min(100, confidence)
    
    def calculate_momentum(self, symbol: str) -> int:
        try:
            with SuppressStdout():
                ticker = yf.Ticker(symbol)
                df = ticker.history(period="5d")
                if df.empty:
                    return 0
                price_change = df['Close'].pct_change().mean() * 100
                price_score = max(-30, min(30, price_change * 10))
                volume_change = df['Volume'].pct_change().mean() * 100
                volume_score = max(-20, min(20, volume_change * 5))
                rsi = RSIIndicator(close=df['Close'], window=14).rsi().iloc[-1]
                if not pd.isna(rsi):
                    if rsi > 70:
                        rsi_score = -20
                    elif rsi < 30:
                        rsi_score = 20
                    else:
                        rsi_score = (rsi - 50) * 0.4
                else:
                    rsi_score = 0
                total_score = price_score + volume_score + rsi_score
                return max(-100, min(100, int(total_score)))
        except:
            return 0
    
    def update_history(self, symbol: str, result: str):
        if symbol not in self.history:
            self.history[symbol] = {'wins': 0, 'losses': 0, 'total': 0}
        self.history[symbol]['total'] += 1
        if result == 'WIN':
            self.history[symbol]['wins'] += 1
        else:
            self.history[symbol]['losses'] += 1
        self.history[symbol]['accuracy'] = (self.history[symbol]['wins'] / self.history[symbol]['total']) * 100

confidence_scorer = SignalConfidenceScorer()

# ==================== ALERT BATCHER ====================
class AlertBatcher:
    def __init__(self):
        self.buffer: List[Dict] = []
        self.last_sent = time.time()
        self.batch_interval = config.BATCH_INTERVAL
        self.max_batch_size = 5
        
    def add_alert(self, alert_type: str, data: Dict):
        self.buffer.append({'type': alert_type, 'data': data, 'timestamp': time.time()})
        if len(self.buffer) >= self.max_batch_size or (time.time() - self.last_sent) > self.batch_interval:
            self.send_batch()
    
    def send_batch(self):
        if not self.buffer:
            return
        signals = [b for b in self.buffer if b['type'] == 'signal']
        news = [b for b in self.buffer if b['type'] == 'news']
        if signals:
            msg = "📦 **SIGNAL BATCH** 📦\n═════════════════════════\n\n"
            for signal in signals:
                data = signal['data']
                msg += f"🔥 <b>#{data['name']}</b> ({data['sentiment']})\n"
                msg += f"💰 Price: ₹{data['price']:,.2f}\n"
                msg += f"🎯 Target: ₹{data['target']:,.2f}\n"
                msg += f"🛑 SL: ₹{data['sl']:,.2f}\n"
                msg += f"📊 Confidence: {data.get('confidence', 0)}%\n\n"
            msg += "═════════════════════════"
            send_telegram_alert(msg)
        if news:
            msg = "📰 **NEWS BATCH** 📰\n═════════════════════════\n\n"
            for news_item in news:
                data = news_item['data']
                if "NEUTRAL" in data['sentiment']:
                    continue
                msg += f"{data['sentiment']} <b>#{data['stock']}</b>\n"
                msg += f"📰 {data['title'][:100]}...\n\n"
            if len(msg) > 100:
                msg += "═════════════════════════"
                send_telegram_alert(msg)
        self.buffer = []
        self.last_sent = time.time()

alert_batcher = AlertBatcher()

# ==================== EXISTING CONFIGURATIONS ====================
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
    "BAJAJ FINANCE": "BAJFINANCE.NS", "BAJFINANCE": "BAJFINANCE.NS", "BAJAJ FINSERV": "BAJFINSV.NS",
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

MACRO_KEYWORDS = [
    "fed", "federal reserve", "fomc", "jerome powell", "interest rate", 
    "rate cut", "rate hike", "repo rate", "reverse repo", "rbi", "mpc", 
    "liquidity", "quantitative easing", "rate pause", "ecb", "boe", "boj",
    "cpi", "core cpi", "ppi", "inflation", "gdp", "pmi", "nfp", "nonfarm payroll", 
    "unemployment", "retail sales", "consumer confidence", "recession", 
    "soft landing", "hard landing", "fiscal deficit", "current account deficit",
    "dxy", "dollar index", "usdinr", "treasury yield", "bond yield", 
    "fii inflow", "fii outflow", "dii buying", "forex reserves", "gst collection", 
    "union budget", "capex",
    "brent crude", "crude oil", "opec", "opec plus", "natural gas", 
    "gold price", "silver price", "copper", "lng", "metals",
    "war", "missile", "tariff", "tsunami", "flood", "geopolitical", 
    "sanctions", "trade war", "export duty", "import duty", "embargo", 
    "supply chain", "blockade",
    "sebi", "f&o ban", "circuit breaker", "block deal", "bulk deal"
]

# ==================== GLOBAL STATE ====================
signal_lock = threading.Lock()
last_signal_state = {}
last_alert_candle_time = {}
seen_news_titles = set()
seen_macro_news_titles = set()
news_watched_stocks = set()
stock_latest_news_time = {}
stock_sentiment_counts = {}
last_news_alert_time = {}
day_news_log = []
day_plus_signals_log = []
TRADE_STATS = {"total_signals": 0, "target_hit": 0, "sl_hit": 0}
ACTIVE_MONITORED_TRADES = []
last_sent_845_date = ""
last_sent_910_date = ""
last_sent_330_date = ""

# ==================== TELEGRAM FUNCTIONS ====================
def send_telegram_alert(message, reply_markup=None):
    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": config.TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code != 200:
            logger.error(f"Telegram API Error: {response.text}")
    except Exception as e:
        logger.error(f"Telegram API Error: {e}")
        monitor.record_api_error()

def send_telegram_photo(image_bytes, caption=""):
    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendPhoto"
    files = {"photo": ("chart.png", image_bytes, "image/png")}
    data = {"chat_id": config.TELEGRAM_CHAT_ID, "caption": caption, "parse_mode": "HTML"}
    try:
        response = requests.post(url, data=data, files=files, timeout=15)
        if response.status_code != 200:
            logger.error(f"Telegram Photo API Error: {response.text}")
    except Exception as e:
        logger.error(f"Telegram Photo API Error: {e}")
        monitor.record_api_error()

def send_telegram_audio(audio_bytes, caption=""):
    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendAudio"
    files = {"audio": ("alert.mp3", audio_bytes, "audio/mpeg")}
    data = {"chat_id": config.TELEGRAM_CHAT_ID, "caption": caption, "parse_mode": "HTML"}
    try:
        response = requests.post(url, data=data, files=files, timeout=15)
        if response.status_code != 200:
            logger.error(f"Telegram Audio API Error: {response.text}")
    except Exception as e:
        logger.error(f"Telegram Audio API Error: {e}")
        monitor.record_api_error()

# ==================== VOICE ALERTS (TTS) ====================
def generate_voice_alert(text: str) -> Optional[bytes]:
    try:
        engine = pyttsx3.init()
        engine.setProperty('rate', 150)
        engine.setProperty('volume', 0.9)
        engine.save_to_file(text, 'temp_alert.wav')
        engine.runAndWait()
        with open('temp_alert.wav', 'rb') as f:
            audio_bytes = f.read()
        os.remove('temp_alert.wav')
        return audio_bytes
    except Exception as e:
        logger.error(f"TTS Error: {e}")
        return None

def send_voice_alert(text):
    audio_bytes = generate_voice_alert(text)
    if audio_bytes:
        send_telegram_audio(audio_bytes, caption="🔊 Voice Alert")

# ==================== AI SENTIMENT ANALYSIS (OpenAI) ====================
def analyze_sentiment_ai(title: str) -> Tuple[str, int]:
    if not OPENAI_AVAILABLE:
        return sentiment_analyzer.analyze(title)[:2]
    try:
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a financial news sentiment analyzer. Respond with only one word: POSITIVE, NEGATIVE, or NEUTRAL."},
                {"role": "user", "content": f"Analyze sentiment: {title}"}
            ],
            max_tokens=10,
            temperature=0.3
        )
        sentiment_text = response.choices[0].message.content.strip().upper()
        if "POSITIVE" in sentiment_text:
            return "🟢 POSITIVE", 1
        elif "NEGATIVE" in sentiment_text:
            return "🔴 NEGATIVE", -1
        else:
            return "⚪ NEUTRAL", 0
    except Exception as e:
        logger.error(f"OpenAI API error: {e}")
        return sentiment_analyzer.analyze(title)[:2]

# ==================== HELPER FUNCTIONS ====================
def is_cloud_platform() -> bool:
    return bool(os.environ.get('RENDER') or os.environ.get('RAILWAY') or os.environ.get('RENDER_GIT_COMMIT'))

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
            logger.error(f"Chart Generation Error: {e}")
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

@retry_on_failure(max_retries=2, delay=1)
def get_accurate_price(symbol: str) -> float:
    cached_price = price_cache.get(symbol)
    if cached_price:
        return cached_price
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
    # Try AI first, fallback to keyword
    if OPENAI_AVAILABLE:
        return analyze_sentiment_ai(title)
    else:
        return sentiment_analyzer.analyze(title)[:2]

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
    news_items = []
    for url in GLOBAL_NEWS_FEEDS:
        try:
            resp = requests.get(url, headers=config.HTTP_HEADERS, timeout=6)
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
                        if "NEUTRAL" not in sent:
                            news_items.append({"title": title, "link": link, "sentiment": sent})
        except Exception:
            pass
    return news_items[:5]

# ==================== TRADE FUNCTIONS ====================
def update_and_check_trade_outcomes():
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
            monitor.record_trade_result('WIN')
            confidence_scorer.update_history(trade["symbol"], 'WIN')
        elif sl_hit:
            TRADE_STATS["sl_hit"] += 1
            monitor.record_trade_result('LOSS')
            confidence_scorer.update_history(trade["symbol"], 'LOSS')
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

# ==================== SIGNAL FUNCTION ====================
def check_3min_plus_signal(symbol: str, display_name: str, is_index: bool = False) -> Optional[SignalData]:
    global last_signal_state, last_alert_candle_time
    with SuppressStdout():
        try:
            current_close = get_accurate_price(symbol)
            if current_close == 0.0:
                return None
            if not is_index and current_close < 200:
                return None
            ticker = yf.Ticker(symbol)
            df = ticker.history(period="1d", interval="3m")
            if df.empty or len(df) < 5:
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
            warning_note = ""
            if vol_ratio < 1.0 and not is_index:
                warning_note = "⚠️ Volume is low (<1.0x SMA)"
            elif vol_ratio >= 2.0 and not is_index:
                warning_note = "🔥 High Volume Confirmation (>2.0x SMA)"
            else:
                warning_note = "✅ Volume Normal"
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
                    if current_direction == "BULLISH":
                        stop_loss = current_close - (atr_val * 1.5)
                        target = current_close + ((current_close - stop_loss) * 1.5)
                    else:
                        stop_loss = current_close + (atr_val * 1.5)
                        target = current_close - ((stop_loss - current_close) * 1.5)
                    risk_per_share = abs(current_close - stop_loss)
                    recommended_qty = int(config.MAX_RISK_PER_TRADE / risk_per_share) if risk_per_share > 0 else 1
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
                        recommended_qty=recommended_qty,
                        confidence=0,
                        momentum_score=0
                    )
                    confidence = confidence_scorer.calculate_confidence(signal_data)
                    momentum = confidence_scorer.calculate_momentum(symbol)
                    signal_data.confidence = confidence
                    signal_data.momentum_score = momentum
                    sig_dict = asdict(signal_data)
                    day_plus_signals_log.append(sig_dict)
                    TRADE_STATS["total_signals"] += 1
                    priority = 'high' if symbol in config.HIGH_PRIORITY_STOCKS else 'medium' if symbol in config.MEDIUM_PRIORITY_STOCKS else 'low'
                    ACTIVE_MONITORED_TRADES.append({
                        "symbol": symbol,
                        "direction": current_direction,
                        "target": target,
                        "sl": stop_loss,
                        "entry_time": datetime.now(IST),
                        "entry_price": current_close,
                        "priority": priority
                    })
                    monitor.record_signal(priority)
                    return signal_data
        except Exception as e:
            logger.error(f"Signal check error for {symbol}: {e}")
            monitor.record_api_error()
    return None

# ==================== NEWS FUNCTIONS ====================
def process_rss_items(soup, max_items: int = 20, age_limit: int = 3600) -> List[Dict]:
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
            if (now_ist - pub_time).total_seconds() > age_limit:
                continue
            quality = news_filter.get_quality_score(link, title)
            if quality < 6:
                continue
            processed_items.append({
                'title': title,
                'link': link,
                'pub_time': pub_time,
                'pub_time_str': pub_time.strftime(config.TIME_FORMAT),
                'quality': quality
            })
        except Exception as e:
            logger.debug(f"Error processing RSS item: {e}")
            continue
    return processed_items

def check_macro_and_global_news():
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
            items = process_rss_items(soup, max_items=15, age_limit=config.MACRO_NEWS_AGE_LIMIT)
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
                        "link": link,
                        "quality": item.get('quality', 5)
                    })
                    monitor.record_macro_news()
        except Exception as e:
            logger.error(f"Error in macro news check: {e}")
            monitor.record_api_error()
    if batch_news_items:
        send_macro_news_batch_alert(batch_news_items, now_ist)

def send_macro_news_batch_alert(batch_news_items: List[Dict], now_ist: datetime):
    msg = (
        f"🚨 <b>[24*7 MACRO & GLOBAL NEWS ALERT]</b> 🚨\n"
        f"📅 <i>{now_ist.strftime(config.DATETIME_FORMAT)}</i>\n"
        f"═════════════════════════\n\n"
    )
    for idx, n_item in enumerate(batch_news_items, 1):
        msg += (
            f"<b>{idx}. Keyword:</b> <code>{n_item['keyword']}</code> | {n_item['sentiment']}\n"
            f"📰 <a href=\"{n_item['link']}\">{n_item['title'][:150]}{'...' if len(n_item['title']) > 150 else ''}</a>\n"
            f"⭐ Quality: {n_item.get('quality', 5)}/10\n\n"
        )
    msg += (
        f"═════════════════════════\n"
        f"🤖 <i>Shambhu's Live Precision Radar Engine</i>"
    )
    send_telegram_alert(msg)

# ==================== MODIFIED ALERT WITH INTERACTIVE BUTTONS, VOICE, DB ====================
def send_instant_plus_signal_alert(sig_dict):
    now_str = datetime.now(IST).strftime(config.DATETIME_FORMAT)
    matched_news = [n for n in day_news_log if n['stock'] == sig_dict['name']]
    news_section = ""
    if matched_news:
        latest_n = matched_news[-1]
        news_html = f'<a href="{latest_n["link"]}">{latest_n["title"]}</a>' if latest_n.get('link') else f'<i>{latest_n["title"]}</i>'
        news_sent = latest_n['sentiment']
        news_section = f"• 📰 <b>Stock News:</b> {news_html}\n• 📊 <b>News Sentiment:</b> {news_sent}\n"
    else:
        news_section = "• 📰 <b>Stock News:</b> <i>No Recent Specific News</i>\n"
    win_rate_summary = get_win_rate_summary_text()
    confidence = sig_dict.get('confidence', 0)
    momentum = sig_dict.get('momentum_score', 0)
    if confidence >= 70:
        confidence_emoji = "🚀 HIGH"
    elif confidence >= 50:
        confidence_emoji = "📈 MEDIUM"
    else:
        confidence_emoji = "⚠️ LOW"
    momentum_emoji = "🟢" if momentum > 0 else "🔴" if momentum < 0 else "⚪"
    momentum_text = f"{momentum_emoji} {abs(momentum)}%" if momentum != 0 else "NEUTRAL"
    msg = (
        f"⚡ <b>[LIVE (+) SIGNAL]</b> ⚡\n"
        f"📅 <i>{now_str}</i>\n"
        f"═════════════════════════\n\n"
        f"🔥 <b>#{sig_dict['name']}</b> ({sig_dict['sentiment']})\n"
        f"{news_section}"
        f"• ⚡ <b>+ Sign Status:</b> ✅ DETECTED ({sig_dict['action']})\n"
        f"• 📢 <b>Indicator Info:</b> <i>{sig_dict['warning_note']}</i>\n"
        f"• 📈 <b>RSI (3m):</b> {sig_dict['rsi']:.1f} (Info only)\n"
        f"• 💰 <b>Current Price:</b> ₹{sig_dict['price']:,.2f}\n\n"
        f"📊 <b>Signal Quality:</b>\n"
        f"• Confidence: <b>{confidence}%</b> {confidence_emoji}\n"
        f"• Momentum: <b>{momentum_text}</b>\n\n"
        f"📌 <b>Other Indicators (Info Only):</b>\n"
        f"• <b>VWAP:</b> {sig_dict['vwap_info']}\n"
        f"• <b>Supertrend:</b> {sig_dict['supertrend_info']}\n\n"
        f"🧮 <b>Risk Management (Max Risk ₹{config.MAX_RISK_PER_TRADE}):</b>\n"
        f"• Risk/Share: ₹{sig_dict['risk_per_share']:.2f}\n"
        f"• Recommended Qty: <b>{sig_dict['recommended_qty']} Shares</b>\n\n"
    )
    if sig_dict['strike'] != "N/A":
        msg += f"• 🎯 <b>Suggested Option:</b> <code>{sig_dict['strike']}</code>\n"
    msg += (
        f"• 🛑 <b>SL:</b> ₹{sig_dict['sl']:,.2f} | 🎯 <b>Target:</b> ₹{sig_dict['target']:,.2f}\n"
        f"═════════════════════════\n"
        f"{win_rate_summary}\n"
        f"═════════════════════════\n"
        f"🤖 <i>Shambhu's Live Precision Radar Engine</i>"
    )
    clean_sym = sig_dict['symbol'].replace('.NS', '')
    # Interactive Buttons
    reply_markup = {
        "inline_keyboard": [
            [{"text": "📊 Live Chart", "url": f"https://in.tradingview.com/chart/?symbol=NSE:{clean_sym}"}],
            [{"text": "🔔 Add Watchlist", "callback_data": f"watch_{clean_sym}"}],
            [{"text": "📰 Full News", "callback_data": f"news_{sig_dict['name']}"}],
            [{"text": "🗑️ Dismiss", "callback_data": "dismiss"}]
        ]
    }
    send_telegram_alert(msg, reply_markup=reply_markup)
    # Chart image
    chart_img = generate_chart_image(sig_dict['symbol'], sig_dict['name'])
    if chart_img:
        caption = f"📊 <b>{sig_dict['name']}</b> ({sig_dict['sentiment']})\n⚡ <b>Action:</b> {sig_dict['action']} | 💰 <b>Price:</b> ₹{sig_dict['price']:,.2f}\n🛑 <b>SL:</b> ₹{sig_dict['sl']:,.2f} | 🎯 <b>Target:</b> ₹{sig_dict['target']:,.2f}\n📊 Confidence: {sig_dict.get('confidence', 0)}%"
        send_telegram_photo(chart_img, caption=caption)
    
    # Voice alert for high confidence
    if confidence >= 80:
        voice_text = f"Alert! {sig_dict['direction']} signal for {sig_dict['name']} at price {sig_dict['price']}. Target {sig_dict['target']}, Stop loss {sig_dict['sl']}."
        send_voice_alert(voice_text)
    
    # Save to Database
    db.save_signal(sig_dict)

def fetch_and_collect_stock_news():
    global seen_news_titles, news_watched_stocks, day_news_log, stock_sentiment_counts, stock_latest_news_time, last_news_alert_time
    now_ist = datetime.now(IST)
    cycle_seen_symbols = set()
    for rss_url in INDIAN_NEWS_FEEDS:
        try:
            resp = requests.get(rss_url, headers=config.HTTP_HEADERS, timeout=8)
            if resp.status_code != 200:
                continue
            soup = BeautifulSoup(resp.content, "xml")
            items = process_rss_items(soup, max_items=20, age_limit=config.STOCK_NEWS_AGE_LIMIT)
            for item in items:
                title = item['title']
                link = item['link']
                pub_time = item['pub_time']
                pub_time_formatted = item['pub_time_str']
                if title:
                    norm_title = normalize_text(title)
                    if norm_title in seen_news_titles:
                        continue
                    display_name, yf_symbol = extract_single_stock_only(title)
                    if display_name and yf_symbol:
                        seen_news_titles.add(norm_title)
                        if yf_symbol in cycle_seen_symbols:
                            continue
                        last_alert_time = last_news_alert_time.get(yf_symbol)
                        if last_alert_time and (now_ist - last_alert_time).total_seconds() < config.NEWS_COOLDOWN_SECONDS:
                            continue
                        sentiment, _ = analyze_sentiment(title)
                        if "NEUTRAL" not in sentiment:
                            stock_latest_news_time[yf_symbol] = pub_time
                            price = get_accurate_price(yf_symbol)
                            #if price < 200:
                               # continue
                            news_watched_stocks.add((display_name, yf_symbol))
                            cycle_seen_symbols.add(yf_symbol)
                            if yf_symbol not in stock_sentiment_counts:
                                stock_sentiment_counts[yf_symbol] = {"pos": 0, "neg": 0}
                            if "POSITIVE" in sentiment:
                                stock_sentiment_counts[yf_symbol]["pos"] += 1
                            else:
                                stock_sentiment_counts[yf_symbol]["neg"] += 1
                            pos_count = stock_sentiment_counts[yf_symbol]["pos"]
                            neg_count = stock_sentiment_counts[yf_symbol]["neg"]
                            marks_str = f"🟢 {pos_count} Pos | 🔴 {neg_count} Neg"
                            news_obj = {
                                "stock": display_name,
                                "symbol": yf_symbol,
                                "price": price,
                                "title": title,
                                "sentiment": sentiment,
                                "time": pub_time_formatted,
                                "link": link,
                                "marks": marks_str,
                                "quality": item.get('quality', 5)
                            }
                            day_news_log.append(news_obj)
                            db.save_news(news_obj)  # Save to DB
                            monitor.record_news()
        except Exception as e:
            logger.error(f"Error fetching news from {rss_url}: {e}")
            monitor.record_api_error()

# ==================== SCHEDULED REPORTS ====================
def send_845_am_premarket_report():
    now_ist = datetime.now(IST)
    macros = fetch_macro_indicators()
    news_items = fetch_clickable_global_news_list()
    msg = f"🌅 <b>08:45 AM PRE-MARKET GLOBAL SENTIMENT REPORT</b> 🌅\n"
    msg += f"📅 <i>{now_ist.strftime(config.DATE_FORMAT)}</i>\n"
    msg += "═════════════════════════\n\n"
    msg += "📊 <b>GLOBAL & MACRO CUES:</b>\n"
    for name, val in macros.items():
        price_str = f"{val['price']:,.2f}"
        chg_str = f"{val['change_pct']:+.2f}%"
        icon = "🟢" if val['change_pct'] >= 0 else "🔴"
        msg += f"• <b>{name}:</b> {price_str} ({icon} {chg_str})\n"
    msg += "\n-----------------------------------------\n\n"
    msg += "🌐 <b>GLOBAL BREAKING NEWS & LINKS:</b>\n"
    if news_items:
        for item in news_items:
            msg += f"• {item['sentiment']}: <a href=\"{item['link']}\">{item['title'][:100]}...</a>\n\n"
    else:
        msg += "• ℹ️ Global news cues stable.\n"
    msg += "═════════════════════════\n"
    msg += "🤖 <i>Shambhu's Live Precision Radar Engine</i>"
    send_telegram_alert(msg)

def send_910_am_table_report():
    now_ist = datetime.now(IST)
    news_24h = []
    nifty_p = get_accurate_price("^NSEI")
    bank_p = get_accurate_price("^NSEBANK")
    sensex_p = get_accurate_price("^BSESN")
    vix_p = get_accurate_price("^INDIAVIX")
    msg = f"📊 <b>09:10 AM INDIAN MARKET SENTIMENT & 24H NEWS</b> 📊\n"
    msg += f"📅 <i>{now_ist.strftime(config.DATE_FORMAT)}</i>\n"
    msg += "═════════════════════════\n\n"
    msg += "🇮🇳 <b>INDIAN MARKET SNAPSHOT:</b>\n"
    msg += f"• <b>NIFTY 50:</b> ₹{nifty_p:,.2f}\n"
    msg += f"• <b>BANK NIFTY:</b> ₹{bank_p:,.2f}\n"
    msg += f"• <b>SENSEX:</b> ₹{sensex_p:,.2f}\n"
    msg += f"• <b>INDIA VIX:</b> {vix_p:.2f}\n"
    msg += "\n-----------------------------------------\n\n"
    for rss_url in INDIAN_NEWS_FEEDS:
        try:
            resp = requests.get(rss_url, headers=config.HTTP_HEADERS, timeout=8)
            if resp.status_code != 200:
                continue
            soup = BeautifulSoup(resp.content, "xml")
            items = process_rss_items(soup, max_items=30, age_limit=86400)
            for item in items:
                title = item['title']
                link = item['link']
                pub_time = item['pub_time']
                is_within_24h = (now_ist - pub_time) <= timedelta(hours=24)
                if is_within_24h and title:
                    display_name, yf_symbol = extract_single_stock_only(title)
                    if display_name and yf_symbol:
                        st_price = get_accurate_price(yf_symbol)
                        if st_price >= 200:
                            sent, _ = analyze_sentiment(title)
                            if "NEUTRAL" not in sent:
                                news_24h.append({
                                    "stock": display_name,
                                    "sentiment": sent,
                                    "title": title,
                                    "link": link,
                                    "quality": item.get('quality', 5)
                                })
        except Exception as e:
            logger.error(f"Error in 9:10 AM report: {e}")
    unique_table = {}
    for item in news_24h:
        if item["stock"] not in unique_table or unique_table[item["stock"]].get('quality', 0) < item.get('quality', 0):
            unique_table[item["stock"]] = item
    msg += "📰 <b>PAST 24-HOURS SPECIFIC STOCK NEWS LINKS (>₹200):</b>\n"
    if unique_table:
        for st, item in sorted(unique_table.items(), key=lambda x: x[1].get('quality', 0), reverse=True)[:10]:
            if item.get('link'):
                msg += f"• <b>#{st}:</b> <a href=\"{item['link']}\">{item['title'][:80]}...</a> ({item['sentiment']}) ⭐{item.get('quality', 5)}/10\n\n"
            else:
                msg += f"• <b>#{st}:</b> {item['title'][:80]}... ({item['sentiment']})\n\n"
    else:
        msg += "ℹ️ <i>No specific stock news detected in the last 24 hours.</i>\n"
    msg += "═════════════════════════\n"
    msg += "🤖 <i>Shambhu's Live Precision Radar Engine</i>"
    send_telegram_alert(msg)

def send_330_pm_closing_summary():
    now_ist = datetime.now(IST)
    win_rate_summary = get_win_rate_summary_text()
    performance_report = monitor.get_status_report()
    msg = f"📊 <b>03:30 PM INTRADAY SUMMARY (9:15 AM to 3:30 PM)</b> 📊\n"
    msg += f"📅 <i>{now_ist.strftime(config.DATE_FORMAT)}</i>\n"
    msg += "═════════════════════════\n\n"
    msg += "📈 <b>INDICES CLOSING PRICES:</b>\n"
    for idx_sym, idx_name in INDICES_MAP.items():
        msg += f"• <b>{idx_name}:</b> ₹{get_accurate_price(idx_sym):,.2f}\n"
    msg += "\n-----------------------------------------\n\n"
    msg += f"{win_rate_summary}\n"
    msg += "-----------------------------------------\n\n"
    msg += f"{performance_report}\n"
    msg += "-----------------------------------------\n\n"
    msg += f"🔥 <b>TODAY'S EMA CROSSOVER (+) SIGNALS ({len(day_plus_signals_log)}):</b>\n"
    if day_plus_signals_log:
        for sig in day_plus_signals_log[-10:]:
            confidence = sig.get('confidence', 0)
            msg += f"• <b>#{sig['name']}</b> ({sig['time']}) -> {sig['sentiment']}\n"
            msg += f"  Price: ₹{sig['price']:,.2f} | Confidence: {confidence}%\n"
    else:
        msg += "• ℹ️ No (+) signals formed during market hours today.\n"
    msg += "\n═════════════════════════\n"
    msg += "🤖 <i>Market Closed. See you tomorrow!</i>"
    send_telegram_alert(msg)
    day_news_log.clear()
    day_plus_signals_log.clear()
    stock_sentiment_counts.clear()
    stock_latest_news_time.clear()
    seen_news_titles.clear()
    seen_macro_news_titles.clear()
    last_news_alert_time.clear()
    TRADE_STATS["total_signals"] = 0
    TRADE_STATS["target_hit"] = 0
    TRADE_STATS["sl_hit"] = 0
    ACTIVE_MONITORED_TRADES.clear()
    price_cache.clear()

# ==================== WEB DASHBOARD (Flask + SocketIO) ====================
flask_app = Flask(__name__)
flask_app.config['SECRET_KEY'] = 'secret!'
socketio = SocketIO(flask_app, cors_allowed_origins="*")

DASHBOARD_HTML = '''
<!DOCTYPE html>
<html>
<head>
    <title>Live Radar Dashboard</title>
    <script src="https://cdn.socket.io/4.5.0/socket.io.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        body { font-family: Arial; margin: 20px; background: #1e1e2e; color: #fff; }
        .card { background: #2d2d44; border-radius: 10px; padding: 15px; margin: 10px 0; border-left: 4px solid #4CAF50; }
        .card.bearish { border-left-color: #f44336; }
        .card.neutral { border-left-color: #ff9800; }
        .card h3 { margin: 0; }
        .card small { color: #aaa; }
        #alerts { max-height: 500px; overflow-y: auto; }
        .row { display: flex; flex-wrap: wrap; }
        .col { flex: 1; min-width: 300px; padding: 10px; }
        .chart-container { background: #2d2d44; border-radius: 10px; padding: 10px; }
    </style>
</head>
<body>
    <h1>📡 Live Radar Dashboard</h1>
    <div class="row">
        <div class="col">
            <h2>📊 Live Signals & News</h2>
            <div id="alerts"></div>
        </div>
        <div class="col">
            <h2>📈 Price Chart</h2>
            <div class="chart-container">
                <canvas id="priceChart" width="400" height="200"></canvas>
            </div>
            <div id="stats"></div>
        </div>
    </div>
    <script>
        const socket = io();
        const alertsDiv = document.getElementById('alerts');
        const statsDiv = document.getElementById('stats');
        let chart = null;
        const ctx = document.getElementById('priceChart').getContext('2d');
        chart = new Chart(ctx, {
            type: 'line',
            data: {
                labels: [],
                datasets: [{ label: 'NIFTY 50', data: [], borderColor: '#4CAF50', fill: false }]
            },
            options: { responsive: true, plugins: { legend: { labels: { color: '#fff' } } } }
        });

        socket.on('new_alert', function(data) {
            const card = document.createElement('div');
            card.className = 'card ' + (data.sentiment.includes('BEARISH') ? 'bearish' : data.sentiment.includes('NEUTRAL') ? 'neutral' : '');
            card.innerHTML = `<h3>${data.name} (${data.sentiment})</h3>
                              <p>Price: ₹${data.price} | Direction: ${data.direction}</p>
                              <small>${data.time}</small>`;
            alertsDiv.prepend(card);
            if (alertsDiv.children.length > 50) alertsDiv.removeChild(alertsDiv.lastChild);
        });

        socket.on('stats_update', function(data) {
            statsDiv.innerHTML = `<p><b>Total Signals:</b> ${data.total_signals} | <b>Wins:</b> ${data.wins}</p>`;
        });

        socket.on('price_update', function(data) {
            if (chart.data.labels.length > 50) {
                chart.data.labels.shift();
                chart.data.datasets[0].data.shift();
            }
            chart.data.labels.push(data.time);
            chart.data.datasets[0].data.push(data.price);
            chart.update();
        });

        fetch('/api/recent').then(r => r.json()).then(data => {
            data.reverse().forEach(alert => {
                const card = document.createElement('div');
                card.className = 'card';
                card.innerHTML = `<h3>${alert.name}</h3><p>${alert.direction} at ₹${alert.price}</p><small>${alert.time}</small>`;
                alertsDiv.appendChild(card);
            });
        });
    </script>
</body>
</html>
'''

@flask_app.route('/')
def dashboard():
    return render_template_string(DASHBOARD_HTML)

@flask_app.route('/api/recent')
def api_recent():
    signals = db.get_recent_signals(20)
    return json.dumps([{'name': s[1], 'direction': s[3], 'price': s[4], 'time': s[8]} for s in signals])

@socketio.on('connect')
def handle_connect():
    logger.info('Client connected')
    stats = db.get_stats()
    emit('stats_update', stats)

def emit_alert_to_web(signal):
    socketio.emit('new_alert', signal)
    stats = db.get_stats()
    socketio.emit('stats_update', stats)

# ==================== MAIN SCAN FUNCTION (Modified to emit to web) ====================
def scan_and_alert():
    global last_sent_845_date, last_sent_910_date, last_sent_330_date
    scan_start = time.time()
    try:
        now_ist = datetime.now(IST)
        current_time = now_ist.strftime("%H:%M")
        today_date = now_ist.strftime("%Y-%m-%d")
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
        check_macro_and_global_news()
        fetch_and_collect_stock_news()
        update_and_check_trade_outcomes()
        if is_market_hours():
            scan_dict = {}
            for index_sym, index_name in INDICES_MAP.items():
                scan_dict[index_sym] = (index_sym, index_name, True)
            for s_name, s_sym in CORE_STOCKS_MAP.items():
                scan_dict[s_sym] = (s_sym, s_name, False)
            for s_name, s_sym in list(news_watched_stocks):
                if s_sym not in scan_dict:
                    scan_dict[s_sym] = (s_sym, s_name, False)
            scan_items = list(scan_dict.values())
            high_priority = []
            medium_priority = []
            low_priority = []
            for item in scan_items:
                sym = item[0]
                if sym in config.HIGH_PRIORITY_STOCKS:
                    high_priority.append(item)
                elif sym in config.MEDIUM_PRIORITY_STOCKS:
                    medium_priority.append(item)
                else:
                    low_priority.append(item)
            executor = pool_manager.get_executor()
            futures = []
            for item in high_priority:
                futures.append(executor.submit(_scan_single_item, item))
            for i in range(0, len(medium_priority), 5):
                batch = medium_priority[i:i+5]
                for item in batch:
                    futures.append(executor.submit(_scan_single_item, item))
                time.sleep(0.5)
            for i in range(0, len(low_priority), 10):
                batch = low_priority[i:i+10]
                for item in batch:
                    futures.append(executor.submit(_scan_single_item, item))
                time.sleep(1)
            for future in futures:
                try:
                    future.result(timeout=3)
                except Exception as e:
                    logger.debug(f"Scan item error: {e}")
    except Exception as e:
        logger.error(f"Scan error: {e}")
        monitor.record_api_error()
    scan_duration = time.time() - scan_start
    monitor.record_scan(scan_duration)
    if monitor.metrics['scans'] % 10 == 0:
        logger.info(f"Performance: {monitor.get_status_report()}")

def _scan_single_item(item):
    sym, name, is_idx = item
    try:
        sig = check_3min_plus_signal(sym, name, is_index=is_idx)
        if sig:
            sig_dict = asdict(sig)
            send_instant_plus_signal_alert(sig_dict)
            emit_alert_to_web(sig_dict)  # Send to web dashboard
    except Exception as e:
        logger.error(f"Error scanning {name}: {e}")

# ==================== GRACEFUL SHUTDOWN ====================
def signal_handler(sig, frame):
    logger.info("🛑 Received shutdown signal. Cleaning up...")
    if not is_cloud_platform():
        try:
            send_telegram_alert("🛑 Radar Engine shutting down gracefully")
        except:
            pass
    else:
        logger.info("Cloud platform detected - silent shutdown (no alert)")
    pool_manager.shutdown()
    logger.info("Cleanup complete. Exiting...")
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

# ==================== HEALTH CHECK ====================
def check_internet_connection() -> bool:
    try:
        requests.get("https://www.google.com", timeout=5)
        return True
    except:
        return False

def run_health_check():
    while True:
        try:
            if not check_internet_connection():
                logger.warning("No internet connection detected")
                if not is_cloud_platform():
                    send_telegram_alert("⚠️ No internet connection detected!")
            if monitor.metrics['scans'] % 100 == 0 and monitor.metrics['scans'] > 0:
                status_msg = monitor.get_status_report()
                if not is_cloud_platform():
                    send_telegram_alert(status_msg)
        except Exception as e:
            logger.error(f"Health check error: {e}")
        time.sleep(3600)

# ==================== FLASK SERVER (SocketIO) ====================
def run_server():
    socketio.run(flask_app, host='0.0.0.0', port=int(os.environ.get('PORT', 8080)), debug=False, use_reloader=False)

# ==================== MAIN EXECUTION ====================
if __name__ == "__main__":
    logger.info("🚀 Starting Shambhu's Enhanced Radar Engine...")
    if is_cloud_platform():
        logger.info("☁️ Running on Cloud Platform (Render/Railway)")
    else:
        logger.info("💻 Running on Local Machine")
    
    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()
    
    health_thread = threading.Thread(target=run_health_check, daemon=True)
    health_thread.start()
    
    # Startup Alert - आता Cloud वर पण नेहमी पाठवा
if not is_cloud_platform():
    try:
        startup_msg = (
            "🚀 <b>Enhanced Radar Engine Active!</b>\n\n"
            "📊 EMA Crossover & 24*7 Macro News Alerts\n"
            "⚡ Interactive Telegram Buttons\n"
            "🤖 AI Sentiment Analysis (if API key set)\n"
            "🔊 Voice Alerts for Critical Signals\n"
            "💾 SQLite Database Storage\n"
            "🌐 Live Web Dashboard\n"
            "🎯 Priority Scanning & Auto-Restart"
        )
        send_telegram_alert(startup_msg)
        logger.info("Startup alert sent to Telegram")
    except Exception as e:
        logger.error(f"Startup alert error: {e}")
else:
    logger.info("Cloud platform - skipping startup alert (to avoid spam)")
    
    while True:
        try:
            time.sleep(config.CHECK_INTERVAL)
            scan_and_alert()
        except KeyboardInterrupt:
            logger.info("Received keyboard interrupt, shutting down...")
            break
        except Exception as e:
            logger.critical(f"Main Loop Critical Error: {e}")
            if not is_cloud_platform():
                try:
                    send_telegram_alert(f"⚠️ System Restarting due to critical error: {str(e)[:100]}")
                except:
                    pass
            time.sleep(10)
            continue
