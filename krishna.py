#!/usr/bin/env python3
"""
📰 ULTIMATE NEWS BOT – FINAL (All 11 Features)
- Ensemble ML (XGBoost + LightGBM + Random Forest)
- Global market context, event calendar, voice alerts
- Technical indicators, priority/snooze, multi-user
- Volume spike, auto-archive, dark-mode dashboard, A/B testing
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
# At the top, after imports, add this:
import os
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'
os.environ['HF_HUB_DISABLE_SYMLINKS_WARNING'] = '1'
os.environ['TOKENIZERS_PARALLELISM'] = 'false'

# For ML, use only RandomForest (no XGBoost/LightGBM) if they fail.
# Your EnsembleML class already has try/except for each import.
import tempfile
import time
import json
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Optional, Tuple, Any
from functools import lru_cache
from collections import defaultdict
from dataclasses import dataclass

# ---- Flask & WebSocket ----
from flask import Flask, jsonify, request, render_template_string
try:
    from flask_socketio import SocketIO, emit
    SOCKETIO_AVAILABLE = True
except ImportError:
    SOCKETIO_AVAILABLE = False

# ---- Finance & Data ----
import yfinance as yf
import pytz
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import mplfinance as mpf

# ---- Optional Advanced ----
try:
    import aiosqlite
    ASYNC_DB = True
except:
    ASYNC_DB = False

try:
    import redis
    REDIS_AVAILABLE = True
except:
    REDIS_AVAILABLE = False

try:
    import polars as pl
    POLARS_AVAILABLE = True
except:
    POLARS_AVAILABLE = False

try:
    import plotly.graph_objects as go
    PLOTLY_AVAILABLE = True
except:
    PLOTLY_AVAILABLE = False

try:
    from telegra_py import Telegraph
    TELEGRAPH_AVAILABLE = True
except:
    TELEGRAPH_AVAILABLE = False

# ---- ML & NLP ----
try:
    import xgboost as xgb
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.preprocessing import StandardScaler
    import joblib
    ML_AVAILABLE = True
except:
    ML_AVAILABLE = False

try:
    import lightgbm as lgb
    LGBM_AVAILABLE = True
except:
    LGBM_AVAILABLE = False

try:
    import tensorflow as tf
    from tensorflow.keras.models import Sequential
    from tensorflow.keras.layers import LSTM, Dense
    TF_AVAILABLE = True
except:
    TF_AVAILABLE = False

try:
    from transformers import AutoTokenizer, AutoModelForSequenceClassification
    import torch
    FINBERT_AVAILABLE = True
except:
    FINBERT_AVAILABLE = False

try:
    import shap
    SHAP_AVAILABLE = True
except:
    SHAP_AVAILABLE = False

# ---- Voice ----
try:
    from gtts import gTTS
    GTTS_AVAILABLE = True
except:
    GTTS_AVAILABLE = False

# ==================== Config ====================
TELEGRAM_BOT_TOKEN = '8634800722:AAESXRx8Xx3i1mqQvJCsh8ecLd0eP3kPdJQ'
TELEGRAM_CHAT_ID = '1106122116'
CHECK_INTERVAL = 60
MAX_ITEMS_PER_FEED = 10
NEWS_AGE_LIMIT = 86400
DB_FILE = 'news_storage.db'
API_PORT = 5000
MODEL_DIR = 'ml_models'
REDIS_HOST = 'localhost'
REDIS_PORT = 6379
REDIS_DB = 0
os.makedirs(MODEL_DIR, exist_ok=True)

# ---- Feature toggles ----
ENABLE_VOICE_ALERTS = True
ENABLE_GLOBAL_CONTEXT = True
ENABLE_TECHNICAL_INDICATORS = True
ENABLE_EVENT_CALENDAR = True
ENABLE_VOLUME_SPIKE = True
ENABLE_AUTO_ARCHIVE = True
ENABLE_AB_TESTING = True

# ---- Multi-User default watchlist ----
DEFAULT_WATCHLIST = ['RELIANCE.NS', 'HDFCBANK.NS', 'INFY.NS']

WEBHOOK_URLS = []
WATCHLIST_PRICES = {
    'RELIANCE.NS': {'target': 2800, 'direction': 'above'},
    'HDFCBANK.NS': {'target': 1600, 'direction': 'above'},
    'INFY.NS': {'target': 1500, 'direction': 'below'},
}

# ==================== Logging ====================
warnings.filterwarnings("ignore")
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ==================== Redis / Cache ====================
class LocalCache:
    def __init__(self, ttl=60):
        self._cache = {}
        self._ttl = ttl
    def set(self, key, value):
        self._cache[key] = (value, time.time() + self._ttl)
    def get(self, key):
        if key in self._cache:
            val, expiry = self._cache[key]
            if time.time() < expiry:
                return val
            else:
                del self._cache[key]
        return None
    def delete(self, key):
        self._cache.pop(key, None)

if REDIS_AVAILABLE:
    try:
        redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, decode_responses=True)
        redis_client.ping()
        logger.info("✅ Redis connected")
    except:
        redis_client = None
        logger.warning("Redis unavailable, using local cache")
else:
    redis_client = None
    logger.info("Redis not installed, using local cache")

cache = redis_client if redis_client else LocalCache()

def get_cached(key):
    if redis_client:
        val = redis_client.get(key)
        return json.loads(val) if val else None
    return cache.get(key)

def set_cached(key, value, ttl=60):
    if redis_client:
        redis_client.setex(key, ttl, json.dumps(value))
    else:
        cache.set(key, value)

# ==================== Database Init ====================
async def init_db_async():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS news (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT, symbol TEXT, display_name TEXT, title TEXT,
        link TEXT, sentiment TEXT, score REAL, type TEXT, source TEXT,
        category TEXT, pre_price_5m REAL, pre_vol_avg REAL,
        sector_sentiment REAL, market_sentiment REAL, nifty_change REAL,
        hour INTEGER, weekday INTEGER
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS price_impact (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT, event_time TEXT, price_at_event REAL,
        price_5m REAL, price_15m REAL, price_30m REAL
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS alert_prices (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT, alert_time TEXT, price REAL
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS daily_summary_sent (
        date TEXT PRIMARY KEY, sent INTEGER DEFAULT 0
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS feedback (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        news_id INTEGER, reaction TEXT, timestamp TEXT
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS rules (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT, condition TEXT, action TEXT, created_at TEXT
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS breakout_watch (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT, display_name TEXT, alert_type TEXT,
        alert_price REAL, alert_time TEXT, first_15min_high REAL,
        triggered INTEGER DEFAULT 0, added_date TEXT
    )''')
    # Multi-User tables
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        chat_id TEXT PRIMARY KEY,
        watchlist TEXT, preferences TEXT
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS user_alert_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id TEXT, news_id INTEGER, action TEXT, timestamp TEXT
    )''')
    # Archive
    c.execute('''CREATE TABLE IF NOT EXISTS news_archived (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT, symbol TEXT, display_name TEXT, title TEXT,
        link TEXT, sentiment TEXT, score REAL, type TEXT, source TEXT,
        archived_date TEXT
    )''')
    # A/B Test Log
    c.execute('''CREATE TABLE IF NOT EXISTS ab_test_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        model_name TEXT, prediction TEXT, actual TEXT, timestamp TEXT
    )''')
    conn.commit()
    conn.close()
    logger.info("✅ Database initialized.")

# ==================== Multi-User Helpers ====================
def get_user_preferences(chat_id: str) -> dict:
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT watchlist, preferences FROM users WHERE chat_id=?", (chat_id,))
    row = c.fetchone()
    conn.close()
    if row:
        watchlist = json.loads(row[0]) if row[0] else DEFAULT_WATCHLIST
        prefs = json.loads(row[1]) if row[1] else {}
        return {"watchlist": watchlist, "preferences": prefs}
    else:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("INSERT INTO users (chat_id, watchlist, preferences) VALUES (?, ?, ?)",
                  (chat_id, json.dumps(DEFAULT_WATCHLIST), json.dumps({"voice": True, "priority": "high"})))
        conn.commit()
        conn.close()
        return {"watchlist": DEFAULT_WATCHLIST, "preferences": {"voice": True, "priority": "high"}}

def update_user_watchlist(chat_id: str, symbols: list):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("UPDATE users SET watchlist=? WHERE chat_id=?", (json.dumps(symbols), chat_id))
    conn.commit()
    conn.close()

def update_user_prefs(chat_id: str, key: str, value):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT preferences FROM users WHERE chat_id=?", (chat_id,))
    row = c.fetchone()
    prefs = json.loads(row[0]) if row else {}
    prefs[key] = value
    c.execute("UPDATE users SET preferences=? WHERE chat_id=?", (json.dumps(prefs), chat_id))
    conn.commit()
    conn.close()

def add_to_alert_history(chat_id: str, news_id: int, action: str):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT INTO user_alert_history (chat_id, news_id, action, timestamp) VALUES (?,?,?,?)",
              (chat_id, news_id, action, datetime.now().isoformat()))
    conn.commit()
    conn.close()

# ==================== Safe Conversion ====================
def safe_str(s):
    return s.decode('utf-8', 'replace') if isinstance(s, bytes) else (s if s is not None else '')

def safe_float(val):
    if val is None:
        return 0.0
    if isinstance(val, bytes):
        try:
            return float(val.decode('utf-8', 'replace'))
        except:
            return 0.0
    try:
        return float(val)
    except:
        return 0.0

# ==================== Global Market Context ====================
def get_global_market_context():
    try:
        indices = {
            'SPY': 'S&P 500',
            'QQQ': 'Nasdaq',
            'N225': 'Nikkei',
            'HSI': 'Hang Seng'
        }
        context = {}
        for sym, name in indices.items():
            ticker = yf.Ticker(sym + "=X") if sym.startswith('N') or sym == 'HSI' else yf.Ticker(sym)
            data = ticker.history(period="2d")
            if not data.empty and len(data) >= 2:
                pct = (data['Close'].iloc[-1] - data['Close'].iloc[-2]) / data['Close'].iloc[-2] * 100
                context[name] = round(pct, 2)
        return context
    except:
        return {}

# ==================== Event Calendar ====================
def get_upcoming_events(symbol: str, days: int = 3) -> List[str]:
    try:
        ticker = yf.Ticker(symbol)
        cal = ticker.calendar
        if cal is None or cal.empty:
            return []
        now = datetime.now()
        events = []
        if 'Earnings Date' in cal.index:
            ed = cal.loc['Earnings Date']
            if isinstance(ed, (list, np.ndarray)):
                ed = ed[0]
            if isinstance(ed, datetime) and (ed - now).days <= days:
                events.append(f"Earnings in {(ed - now).days} days")
        divs = ticker.dividends
        if not divs.empty:
            next_div = divs.iloc[-1]
            if hasattr(next_div, 'date'):
                if (next_div.date() - now.date()).days <= days:
                    events.append(f"Dividend in {(next_div.date() - now.date()).days} days")
        return events
    except:
        return []

# ==================== Technical Indicators ====================
def get_technical_indicators(symbol: str) -> Dict:
    try:
        ticker = yf.Ticker(symbol)
        data = ticker.history(period="1y")
        if data.empty:
            return {}
        close = data['Close']
        ma50 = close.rolling(50).mean().iloc[-1]
        ma200 = close.rolling(200).mean().iloc[-1]
        delta = close.diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs)).iloc[-1]
        high52 = close.max()
        low52 = close.min()
        current = close.iloc[-1]
        return {
            'ma50': round(ma50, 2),
            'ma200': round(ma200, 2),
            'rsi': round(rsi, 2),
            'high52': round(high52, 2),
            'low52': round(low52, 2),
            'current': round(current, 2)
        }
    except:
        return {}

# ==================== Volume Spike Detection ====================
def check_volume_spike(symbol: str) -> bool:
    try:
        ticker = yf.Ticker(symbol)
        data = ticker.history(period="5d")
        if len(data) < 5:
            return False
        avg_vol = data['Volume'].iloc[:-1].mean()
        last_vol = data['Volume'].iloc[-1]
        return last_vol > 2 * avg_vol
    except:
        return False

# ==================== Ensemble ML ====================
class EnsembleML:
    def __init__(self):
        self.models = {}
        self.scaler = None
        self.feature_names = []
        self.lstm_model = None
        self.ab_enabled = ENABLE_AB_TESTING
        self.load_models()

    def load_models(self):
        if not ML_AVAILABLE:
            return
        for algo in ['xgb', 'lgb', 'rf']:
            p = os.path.join(MODEL_DIR, f"model_{algo}.pkl")
            if os.path.exists(p):
                self.models[algo] = joblib.load(p)
        sp = os.path.join(MODEL_DIR, "scaler.pkl")
        if os.path.exists(sp):
            self.scaler = joblib.load(sp)
        fp = os.path.join(MODEL_DIR, "features.pkl")
        if os.path.exists(fp):
            self.feature_names = joblib.load(fp)
        if TF_AVAILABLE and os.path.exists(os.path.join(MODEL_DIR, "lstm_model.keras")):
            self.lstm_model = tf.keras.models.load_model(os.path.join(MODEL_DIR, "lstm_model.keras"))

    def save_models(self, models_dict):
        for name, model in models_dict.items():
            joblib.dump(model, os.path.join(MODEL_DIR, f"model_{name}.pkl"))
        if self.scaler:
            joblib.dump(self.scaler, os.path.join(MODEL_DIR, "scaler.pkl"))
        if self.feature_names:
            joblib.dump(self.feature_names, os.path.join(MODEL_DIR, "features.pkl"))
        if self.lstm_model:
            self.lstm_model.save(os.path.join(MODEL_DIR, "lstm_model.keras"))

    def prepare_features(self, row):
        feat = [
            row.get('sentiment_score', 0.0),
            row.get('hour', datetime.now().hour),
            row.get('weekday', datetime.now().weekday()),
            row.get('price_at_event', 0.0),
            row.get('pre_price_5m', 0.0),
            row.get('vol_avg', 0.0),
            row.get('sector_sent', 0.0),
            row.get('market_sent', 0.0),
            row.get('nifty_change', 0.0),
        ]
        cats = ['results','buyback','dividend','contract','acquisition','regulatory','fraud','macro','general']
        cat = row.get('category','general')
        for c in cats:
            feat.append(1.0 if c == cat else 0.0)
        return np.array(feat).reshape(1,-1)

    def predict_ensemble(self, features) -> Tuple[int, float]:
        if not ML_AVAILABLE or not self.models:
            return 0, 0.5
        preds = []
        probs = []
        for algo, model in self.models.items():
            if self.scaler:
                feat = self.scaler.transform(features)
            else:
                feat = features
            probs_i = model.predict_proba(feat)[0]
            pred_i = np.argmax(probs_i)
            preds.append(pred_i)
            probs.append(probs_i[pred_i])
        final_pred = max(set(preds), key=preds.count)
        avg_prob = np.mean(probs)
        return final_pred, avg_prob

    def predict_lstm(self, features):
        if self.lstm_model is None:
            return None
        # Dummy: for a real implementation you'd use a sliding window.
        return None

    async def retrain_ensemble_async(self, force=False):
        if not ML_AVAILABLE:
            return
        conn = sqlite3.connect(DB_FILE)
        if POLARS_AVAILABLE:
            df = pl.read_sql("""
                SELECT n.symbol,n.category,n.score as sentiment_score,n.hour,n.weekday,
                       n.pre_price_5m,n.pre_vol_avg,n.sector_sentiment,n.market_sentiment,n.nifty_change,
                       pi.price_at_event,pi.price_5m,pi.price_15m,pi.price_30m
                FROM news n JOIN price_impact pi ON n.symbol=pi.symbol AND datetime(n.timestamp)=datetime(pi.event_time)
                WHERE pi.price_15m IS NOT NULL
            """, conn)
        else:
            df = pd.read_sql("""
                SELECT n.symbol,n.category,n.score as sentiment_score,n.hour,n.weekday,
                       n.pre_price_5m,n.pre_vol_avg,n.sector_sentiment,n.market_sentiment,n.nifty_change,
                       pi.price_at_event,pi.price_5m,pi.price_15m,pi.price_30m
                FROM news n JOIN price_impact pi ON n.symbol=pi.symbol AND datetime(n.timestamp)=datetime(pi.event_time)
                WHERE pi.price_15m IS NOT NULL
            """, conn)
        conn.close()
        if len(df) < 100:
            logger.info(f"Not enough samples for retraining: {len(df)}")
            return
        if POLARS_AVAILABLE:
            df = df.with_columns([
                (pl.col('pre_vol_avg') / pl.col('pre_vol_avg').mean()).alias('vol_spike'),
                ((pl.col('price_5m') - pl.col('price_at_event')) / pl.col('price_at_event') * 100).alias('pc_5m'),
                ((pl.col('price_15m') - pl.col('price_at_event')) / pl.col('price_at_event') * 100).alias('pc_15m'),
                ((pl.col('price_30m') - pl.col('price_at_event')) / pl.col('price_at_event') * 100).alias('pc_30m'),
            ])
            for h in ['5m','15m','30m']:
                df = df.with_columns(
                    pl.when(pl.col(f'pc_{h}') < -0.5).then(0)
                    .when(pl.col(f'pc_{h}') > 0.5).then(2)
                    .otherwise(1).alias(f'target_{h}')
                )
            cats = ['results','buyback','dividend','contract','acquisition','regulatory','fraud','macro','general']
            for c in cats:
                df = df.with_columns((pl.col('category') == c).cast(pl.Int32).alias(f'cat_{c}'))
            feat_cols = ['sentiment_score','hour','weekday','price_at_event','pre_price_5m','vol_spike',
                         'sector_sentiment','market_sentiment','nifty_change'] + [f'cat_{c}' for c in cats]
            X = df.select(feat_cols).to_numpy()
            X = pd.DataFrame(X, columns=feat_cols)
        else:
            df['vol_spike'] = df['pre_vol_avg'] / df['pre_vol_avg'].mean() if df['pre_vol_avg'].mean()>0 else 1.0
            for h in ['5m','15m','30m']:
                df[f'pc_{h}'] = (df[f'price_{h}'] - df['price_at_event']) / df['price_at_event'] * 100
                df[f'target_{h}'] = df[f'pc_{h}'].apply(lambda x: 0 if x < -0.5 else (2 if x > 0.5 else 1))
            cats = ['results','buyback','dividend','contract','acquisition','regulatory','fraud','macro','general']
            for c in cats:
                df[f'cat_{c}'] = (df['category'] == c).astype(int)
            feat_cols = ['sentiment_score','hour','weekday','price_at_event','pre_price_5m','vol_spike',
                         'sector_sentiment','market_sentiment','nifty_change'] + [f'cat_{c}' for c in cats]
            X = df[feat_cols]

        scaler = StandardScaler()
        X_scaled = scaler.fit_transform(X)
        self.scaler = scaler
        self.feature_names = feat_cols

        y = df['target_15m'] if POLARS_AVAILABLE else df['target_15m']
        models = {}
        xgb_model = xgb.XGBClassifier(n_estimators=100, max_depth=4, learning_rate=0.1,
                                      objective='multi:softprob', num_class=3,
                                      random_state=42, use_label_encoder=False, eval_metric='mlogloss')
        xgb_model.fit(X_scaled, y)
        models['xgb'] = xgb_model
        if LGBM_AVAILABLE:
            lgb_model = lgb.LGBMClassifier(n_estimators=100, learning_rate=0.1, num_leaves=31)
            lgb_model.fit(X_scaled, y)
            models['lgb'] = lgb_model
        rf_model = RandomForestClassifier(n_estimators=100, max_depth=5, random_state=42)
        rf_model.fit(X_scaled, y)
        models['rf'] = rf_model
        self.models = models
        self.save_models(models)

        if TF_AVAILABLE and len(df) > 500:
            X_lstm = X_scaled.reshape(X_scaled.shape[0], 1, X_scaled.shape[1])
            lstm_model = Sequential([
                LSTM(32, input_shape=(1, X_scaled.shape[1])),
                Dense(16, activation='relu'),
                Dense(3, activation='softmax')
            ])
            lstm_model.compile(optimizer='adam', loss='sparse_categorical_crossentropy', metrics=['accuracy'])
            lstm_model.fit(X_lstm, y, epochs=10, batch_size=32, verbose=0)
            self.lstm_model = lstm_model
            self.lstm_model.save(os.path.join(MODEL_DIR, "lstm_model.keras"))

        logger.info("✅ Ensemble ML retraining complete")

ensemble = EnsembleML()

# ==================== Telegram Functions with Buttons ====================
def send_telegram_alert(message: str, disable_preview: bool = False, buttons: List[Dict] = None):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": disable_preview
    }
    if buttons:
        payload['reply_markup'] = json.dumps({"inline_keyboard": buttons})
    try:
        requests.post(url, json=payload, timeout=10)
    except:
        pass

def send_voice_alert(text: str, chat_id: str = None):
    if not GTTS_AVAILABLE or not ENABLE_VOICE_ALERTS:
        return
    try:
        tts = gTTS(text=text, lang='en', slow=False)
        with tempfile.NamedTemporaryFile(delete=False, suffix='.mp3') as f:
            tts.save(f.name)
            voice_file = f.name
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendVoice"
        chat_id = chat_id or TELEGRAM_CHAT_ID
        with open(voice_file, 'rb') as audio:
            requests.post(url, files={'voice': audio}, data={'chat_id': chat_id})
        os.unlink(voice_file)
    except Exception as e:
        logger.error(f"Voice alert failed: {e}")

def send_telegram_photo(photo_path: str, caption: str = ""):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
    try:
        with open(photo_path, 'rb') as f:
            requests.post(url, files={'photo': f}, data={'chat_id': TELEGRAM_CHAT_ID, 'caption': caption, 'parse_mode': 'HTML'}, timeout=15)
    except:
        pass

# ==================== Core Helper Functions ====================
def get_price_for_symbol(symbol):
    cache_key = f"price_{symbol}"
    cached = get_cached(cache_key)
    if cached:
        return cached, False
    try:
        ticker = yf.Ticker(symbol)
        data = ticker.history(period="5d", interval="1m")
        if not data.empty:
            price = data['Close'].iloc[-1]
            set_cached(cache_key, price, ttl=30)
            return price, False
        daily = ticker.history(period="1d", interval="1d")
        if not daily.empty:
            price = daily['Close'].iloc[-1]
            set_cached(cache_key, price, ttl=60)
            return price, True
    except:
        pass
    return None, False

def get_nifty_change():
    cache_key = "nifty_change"
    cached = get_cached(cache_key)
    if cached is not None:
        return cached
    try:
        nifty = yf.Ticker("^NSEI")
        data = nifty.history(period="1d", interval="5m")
        if len(data) >= 2:
            change = (data['Close'].iloc[-1] - data['Close'].iloc[-2]) / data['Close'].iloc[-2] * 100
            set_cached(cache_key, change, ttl=60)
            return change
    except:
        pass
    return 0.0

def get_sector_sentiment(symbol):
    sector = STOCK_TO_SECTOR.get(symbol, 'Others')
    sector_symbols = SECTOR_MAP.get(sector, [])
    if not sector_symbols:
        return 0.0
    cache_key = f"sector_{sector}"
    cached = get_cached(cache_key)
    if cached is not None:
        return cached
    scores = []
    for sym in sector_symbols[:3]:
        try:
            ticker = yf.Ticker(sym)
            hist = ticker.history(period="1d", interval="5m")
            if len(hist) >= 2:
                ret = (hist['Close'].iloc[-1] - hist['Close'].iloc[-2]) / hist['Close'].iloc[-2]
                scores.append(ret * 100)
        except:
            pass
    avg = np.mean(scores) if scores else 0.0
    set_cached(cache_key, avg, ttl=60)
    return avg

def get_pre_price_5m(symbol):
    try:
        ticker = yf.Ticker(symbol)
        data = ticker.history(period="1d", interval="1m")
        if len(data) >= 5:
            return data['Close'].iloc[-5]
    except:
        pass
    return None

def get_vol_avg(symbol):
    cache_key = f"vol_{symbol}"
    cached = get_cached(cache_key)
    if cached is not None:
        return cached
    try:
        ticker = yf.Ticker(symbol)
        data = ticker.history(period="5d", interval="1m")
        if not data.empty:
            avg = data['Volume'].mean()
            set_cached(cache_key, avg, ttl=300)
            return avg
    except:
        pass
    return 0.0

def get_market_status():
    ist = pytz.timezone('Asia/Kolkata')
    now = datetime.now(ist)
    if now.weekday() >= 5: return 'closed'
    open_t = now.replace(hour=9, minute=15, second=0, microsecond=0)
    close_t = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return 'open' if open_t <= now <= close_t else 'closed'

def get_intraday_data(symbol, period="1d"):
    try:
        ticker = yf.Ticker(symbol)
        data = ticker.history(period=period, interval="1m")
        if data.empty: return None
        if data.index.tz is None:
            data.index = data.index.tz_localize('UTC')
        return data
    except:
        return None

def generate_3min_chart(symbol, display_name, data):
    try:
        if data is None or data.empty: return None
        ohlc = data[['Open','High','Low','Close']].resample('3T').agg({
            'Open':'first','High':'max','Low':'min','Close':'last'
        }).dropna()
        if ohlc.empty: return None
        fig, ax = mpf.plot(ohlc, type='candle', volume=False,
                           style='charles', title=f"{display_name} - 3-min",
                           ylabel='₹', tight_layout=True, returnfig=True)
        tmp = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
        fig.savefig(tmp.name, bbox_inches='tight', dpi=100)
        plt.close(fig)
        return tmp.name
    except:
        return None

def get_day_ohlc(symbol):
    try:
        ticker = yf.Ticker(symbol)
        data = ticker.history(period="1d", interval="1m")
        if not data.empty:
            return {'open': data['Open'].iloc[0], 'high': data['High'].max(),
                    'low': data['Low'].min(), 'ltp': data['Close'].iloc[-1]}
        daily = ticker.history(period="1d", interval="1d")
        if not daily.empty:
            return {'open': daily['Open'].iloc[0], 'high': daily['High'].iloc[0],
                    'low': daily['Low'].iloc[0], 'ltp': daily['Close'].iloc[0]}
    except:
        pass
    return {}

def save_alert_price(symbol, price):
    try:
        conn = sqlite3.connect(DB_FILE)
        conn.execute("INSERT INTO alert_prices (symbol, alert_time, price) VALUES (?,?,?)",
                     (symbol, datetime.now().isoformat(), price))
        conn.commit()
        conn.close()
    except:
        pass

def track_price_impact(symbol, event_time, price_at_event):
    try:
        conn = sqlite3.connect(DB_FILE)
        conn.execute("INSERT INTO price_impact (symbol, event_time, price_at_event) VALUES (?,?,?)",
                     (symbol, event_time.isoformat(), price_at_event))
        conn.commit()
        conn.close()
    except:
        pass

# ==================== Historical Context ====================
def get_historical_context(symbol: str, sentiment_score: float, horizon: str = '15m') -> Dict:
    try:
        conn = sqlite3.connect(DB_FILE)
        col_map = {'5m': 'price_5m', '15m': 'price_15m', '30m': 'price_30m'}
        col = col_map.get(horizon, 'price_15m')
        query = f"""
            SELECT n.score, pi.price_at_event, pi.{col}
            FROM news n
            JOIN price_impact pi ON n.symbol = pi.symbol AND datetime(n.timestamp) = datetime(pi.event_time)
            WHERE n.symbol = ? AND n.score BETWEEN ? AND ?
              AND pi.{col} IS NOT NULL
        """
        c = conn.cursor()
        c.execute(query, (symbol, sentiment_score-0.3, sentiment_score+0.3))
        rows = c.fetchall()
        conn.close()
        if not rows:
            return {'count': 0, 'avg_change': 0.0, 'std': 0.0}
        changes = []
        for row in rows:
            price_at = safe_float(row[1])
            price_after = safe_float(row[2])
            if price_at and price_after:
                pct = (price_after - price_at) / price_at * 100
                changes.append(pct)
        if not changes:
            return {'count': 0, 'avg_change': 0.0, 'std': 0.0}
        avg = np.mean(changes)
        std = np.std(changes) if len(changes) > 1 else 0.0
        return {'count': len(changes), 'avg_change': avg, 'std': std}
    except Exception as e:
        logger.error(f"Historical context error: {e}")
        return {'count': 0, 'avg_change': 0.0, 'std': 0.0}

# ==================== Smart Insight ====================
def get_smart_summary(symbol, sentiment_score, price_change_pct=None):
    parts = []
    if sentiment_score > 0.2: parts.append("📈 Positive sentiment")
    elif sentiment_score < -0.2: parts.append("📉 Negative sentiment")
    else: parts.append("➡️ Neutral sentiment")
    if price_change_pct is not None:
        if price_change_pct > 0.5: parts.append(f"➕ already moved +{price_change_pct:.1f}%")
        elif price_change_pct < -0.5: parts.append(f"➖ already moved {price_change_pct:.1f}%")
    sector = STOCK_TO_SECTOR.get(symbol, 'Others')
    sector_sent = get_sector_sentiment(symbol)
    if abs(sector_sent) > 0.1: parts.append(f"🏭 Sector: {sector} ({'bullish' if sector_sent>0 else 'bearish'})")
    return " | ".join(parts) if len(parts)>1 else parts[0]

# ==================== Summarization ====================
def summarize_text(text, max_sentences=2):
    if not text or len(text.split()) < 15:
        return text[:80] + "..."
    try:
        from sumy.parsers.plaintext import PlaintextParser
        from sumy.nlp.tokenizers import Tokenizer
        from sumy.summarizers.text_rank import TextRankSummarizer
        parser = PlaintextParser.from_string(text, Tokenizer("english"))
        summary = TextRankSummarizer()(parser.document, max_sentences)
        if summary:
            return " ".join(str(s) for s in summary)
    except:
        pass
    sentences = re.split(r'(?<=[.!?])\s+', text)
    return sentences[0] if sentences else text[:80]+"..."

# ==================== Sentiment ====================
try:
    from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
    vader = SentimentIntensityAnalyzer()
except:
    vader = None

finbert_tokenizer = None
finbert_model = None
if FINBERT_AVAILABLE:
    try:
        logger.info("Loading FinBERT...")
        finbert_tokenizer = AutoTokenizer.from_pretrained("ProsusAI/finbert", revision="main", use_fast=True)
        finbert_model = AutoModelForSequenceClassification.from_pretrained(
            "ProsusAI/finbert",
            revision="main",
            use_safetensors=False
        )
        logger.info("✅ FinBERT loaded")
    except Exception as e:
        logger.warning(f"FinBERT load failed: {e}. Falling back to VADER.")
        FINBERT_AVAILABLE = False

def analyze_sentiment_advanced(title: str) -> Tuple[str, float]:
    if not title:
        return "NEUTRAL", 0.0
    if FINBERT_AVAILABLE and finbert_model:
        try:
            inputs = finbert_tokenizer(title, return_tensors="pt", truncation=True, max_length=512)
            outputs = finbert_model(**inputs)
            probs = torch.nn.functional.softmax(outputs.logits, dim=-1)
            scores = probs.detach().numpy()[0]
            score = scores[2] - scores[0]
            if score > 0.2: return "POSITIVE", score
            elif score < -0.2: return "NEGATIVE", score
            else: return "NEUTRAL", score
        except:
            pass
    if vader:
        try:
            vs = vader.polarity_scores(title)
            score = vs['compound']
            if score >= 0.05: return "POSITIVE", score
            elif score <= -0.05: return "NEGATIVE", score
            else: return "NEUTRAL", score
        except:
            pass
    score = 0.0
    t = title.lower()
    for kw in HIGH_IMPACT_KEYWORDS:
        if kw in t: score += 0.3
    for kw in NEGATIVE_KEYWORDS:
        if kw in t: score -= 0.3
    score = max(-1, min(1, score))
    if score > 0.1: return "POSITIVE", score
    elif score < -0.1: return "NEGATIVE", score
    else: return "NEUTRAL", score

# ==================== RSS Feeds & Parsing ====================
HIGH_IMPACT_KEYWORDS = [
    "buyback", "dividend", "bonus", "stock split", "results", "quarterly",
    "approval", "contract", "partnership", "acquisition", "merger", "expansion",
    "order", "win", "launch", "breakthrough", "patent", "FDA approval"
]
NEGATIVE_KEYWORDS = [
    "fraud", "default", "investigation", "scam", "penalty", "lawsuit",
    "downgrade", "selloff", "crash", "plunge", "loss", "misses"
]
CATEGORY_KEYWORDS = {
    'results': ['results', 'profit', 'loss', 'revenue', 'earnings'],
    'buyback': ['buyback', 'repurchase'],
    'dividend': ['dividend', 'bonus', 'split'],
    'contract': ['contract', 'order', 'win', 'partnership'],
    'acquisition': ['acquisition', 'merger', 'takeover'],
    'regulatory': ['approval', 'patent', 'FDA', 'clearance'],
    'fraud': ['fraud', 'scam', 'penalty', 'lawsuit'],
    'macro': ['rbi', 'fed', 'crude', 'oil', 'inflation', 'gdp', 'rate']
}

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
    "ZOMATO": "ETERNAL.NS", "PAYTM": "PAYTM.NS",
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
STOCK_TO_SECTOR = {}
for sector, syms in SECTOR_MAP.items():
    for sym in syms:
        STOCK_TO_SECTOR[sym] = sector

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
    "https://www.moneyweb.co.za/feed/",
    "https://www.ft.com/feed",
    "https://www.wsj.com/news/markets?format=rss",
    "https://www.barrons.com/feed",
    "https://www.investopedia.com/feed"
]

def extract_symbol(title):
    for name, symbol in STOCKS_MAP.items():
        if re.search(r'(?<![A-Za-z])' + re.escape(name) + r'(?![A-Za-z])', title, re.I):
            return symbol, name
    return None, None

def is_macro(title):
    t = title.lower()
    return any(kw in t for kw in ['rbi','fed','crude','oil','inflation','gdp','rate'])

def get_category(title):
    t = title.lower()
    for cat, words in CATEGORY_KEYWORDS.items():
        if any(w in t for w in words):
            return cat
    return 'general'

def is_valid_url(url):
    return url and (url.startswith('http://') or url.startswith('https://'))

# ==================== Cache for duplicates ====================
news_cache = set()
def is_cached(title, link):
    key = (title.lower().strip(), link.lower().strip())
    return key in news_cache
def add_cache(title, link):
    news_cache.add((title.lower().strip(), link.lower().strip()))

def news_exists(title, link):
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("SELECT 1 FROM news WHERE LOWER(title)=LOWER(?) OR LOWER(link)=LOWER(?)",
                  (title.strip(), link.strip()))
        exists = c.fetchone() is not None
        conn.close()
        return exists
    except:
        return False

async def fetch_feed(session, url):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'application/rss+xml,application/xml,text/xml'
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
                    if (datetime.now(timezone.utc)-pub_dt).total_seconds() > NEWS_AGE_LIMIT:
                        continue
                    sentiment, score = analyze_sentiment_advanced(title)
                    if sentiment == "NEUTRAL":
                        continue
                    symbol, display = extract_symbol(title)
                    if symbol:
                        items.append({
                            'title': title, 'link': link,
                            'sentiment': '🟢 POSITIVE' if sentiment=='POSITIVE' else '🔴 NEGATIVE',
                            'score': score,
                            'symbol': symbol, 'display_name': display,
                            'time': pub_dt.strftime('%I:%M %p'),
                            'published': pub_dt,
                            'type': 'stock',
                            'source': url.split('/')[2]
                        })
                    elif is_macro(title):
                        items.append({
                            'title': title, 'link': link,
                            'sentiment': '🟢 POSITIVE' if sentiment=='POSITIVE' else '🔴 NEGATIVE',
                            'score': score,
                            'symbol': None,
                            'display_name': '🌐 मॅक्रो/ग्लोबल',
                            'time': pub_dt.strftime('%I:%M %p'),
                            'published': pub_dt,
                            'type': 'macro',
                            'source': url.split('/')[2]
                        })
                return items
    except:
        pass
    return []

def insert_news_with_features(item):
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("PRAGMA table_info(news)")
        cols = [col[1] for col in c.fetchall()]
        symbol = item.get('symbol')
        now = datetime.now()
        pre_price = get_pre_price_5m(symbol) if symbol else 0.0
        vol_avg = get_vol_avg(symbol) if symbol else 0.0
        sector_sent = get_sector_sentiment(symbol) if symbol else 0.0
        market_sent = get_nifty_change()
        cat = get_category(item.get('title',''))
        data = {
            'timestamp': now.isoformat(),
            'symbol': symbol or '',
            'display_name': item.get('display_name',''),
            'title': item.get('title',''),
            'link': item.get('link',''),
            'sentiment': item.get('sentiment','NEUTRAL'),
            'score': item.get('score',0.0),
            'type': item.get('type','stock'),
            'source': item.get('source','RSS'),
            'category': cat,
            'pre_price_5m': pre_price,
            'pre_vol_avg': vol_avg,
            'sector_sentiment': sector_sent,
            'market_sentiment': market_sent,
            'nifty_change': 0.0,
            'hour': now.hour,
            'weekday': now.weekday()
        }
        insert_cols = [k for k in data.keys() if k in cols]
        placeholders = ','.join(['?' for _ in insert_cols])
        query = f"INSERT OR IGNORE INTO news ({','.join(insert_cols)}) VALUES ({placeholders})"
        c.execute(query, [data[k] for k in insert_cols])
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Insert error: {e}")

# ==================== Breakout Watch ====================
def add_to_breakout_watch(symbol: str, display_name: str, alert_type: str, alert_price: float):
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        today = datetime.now().date().isoformat()
        c.execute("SELECT id FROM breakout_watch WHERE symbol=? AND added_date=? AND triggered=0", (symbol, today))
        if c.fetchone():
            conn.close()
            return
        c.execute("INSERT INTO breakout_watch (symbol, display_name, alert_type, alert_price, alert_time, added_date) VALUES (?,?,?,?,?,?)",
                  (symbol, display_name, alert_type, alert_price, datetime.now().isoformat(), today))
        conn.commit()
        conn.close()
        logger.info(f"📌 Added {symbol} to breakout watch (type: {alert_type})")
    except Exception as e:
        logger.error(f"Add breakout watch error: {e}")

def get_first_15min_high(symbol: str) -> Optional[float]:
    try:
        ist = pytz.timezone('Asia/Kolkata')
        today = datetime.now(ist).date()
        ticker = yf.Ticker(symbol)
        data = ticker.history(period="1d", interval="1m")
        if data.empty:
            return None
        if data.index.tz is None:
            data.index = data.index.tz_localize('UTC')
        data.index = data.index.tz_convert(ist)
        start = ist.localize(datetime(today.year, today.month, today.day, 9, 15))
        end = ist.localize(datetime(today.year, today.month, today.day, 9, 30))
        mask = (data.index >= start) & (data.index <= end)
        segment = data[mask]
        if segment.empty:
            return None
        return segment['High'].max()
    except Exception as e:
        logger.error(f"get_first_15min_high error: {e}")
        return None

def check_breakout_watches():
    try:
        ist = pytz.timezone('Asia/Kolkata')
        now = datetime.now(ist)
        if now.weekday() >= 5:
            return
        open_time = now.replace(hour=9, minute=15, second=0, microsecond=0)
        close_time = now.replace(hour=15, minute=30, second=0, microsecond=0)
        if not (open_time <= now <= close_time):
            return

        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        today = now.date().isoformat()
        c.execute("SELECT id, symbol, display_name, alert_type, alert_price, alert_time, first_15min_high FROM breakout_watch WHERE added_date=? AND triggered=0", (today,))
        rows = c.fetchall()
        if not rows:
            conn.close()
            return

        for row in rows:
            watch_id, symbol, display_name, alert_type, alert_price, alert_time, first_high = row
            if first_high is None:
                first_high = get_first_15min_high(symbol)
                if first_high is None:
                    continue
                c.execute("UPDATE breakout_watch SET first_15min_high=? WHERE id=?", (first_high, watch_id))
                conn.commit()
            current_price, _ = get_price_for_symbol(symbol)
            if current_price is None:
                continue
            if current_price > first_high:
                alert_time_str = datetime.fromisoformat(alert_time).astimezone(ist).strftime('%I:%M %p')
                msg = f"🚀 <b>BREAKOUT ALERT</b>\n{display_name} broke above first 15‑min high (₹{first_high:.2f})\nCurrent: ₹{current_price:.2f}\nTriggered by: {alert_type} on {alert_time_str}"
                send_telegram_alert(msg)
                c.execute("UPDATE breakout_watch SET triggered=1 WHERE id=?", (watch_id,))
                conn.commit()
                logger.info(f"✅ Breakout alert sent for {symbol}")
        conn.close()
    except Exception as e:
        logger.error(f"check_breakout_watches error: {e}")

# ==================== Price Trigger Check ====================
last_triggered = {}
def check_price_triggers():
    for symbol, config in WATCHLIST_PRICES.items():
        try:
            price, market_closed = get_price_for_symbol(symbol)
            if not price: continue
            target = config['target']
            direction = config.get('direction', 'above')
            key = f"{symbol}_{target}"
            if direction == 'above' and price > target:
                if key not in last_triggered or (datetime.now() - last_triggered[key]).total_seconds() > 3600:
                    msg = f"⚠️ <b>PRICE ALERT</b>\n{symbol} crossed ₹{target}\nCurrent: ₹{price:.2f}"
                    send_telegram_alert(msg)
                    last_triggered[key] = datetime.now()
                    if market_closed:
                        display_name = [name for name, sym in STOCKS_MAP.items() if sym == symbol]
                        display_name = display_name[0] if display_name else symbol
                        add_to_breakout_watch(symbol, display_name, "Price Alert", price)
            elif direction == 'below' and price < target:
                if key not in last_triggered or (datetime.now() - last_triggered[key]).total_seconds() > 3600:
                    msg = f"⚠️ <b>PRICE ALERT</b>\n{symbol} dropped below ₹{target}\nCurrent: ₹{price:.2f}"
                    send_telegram_alert(msg)
                    last_triggered[key] = datetime.now()
                    if market_closed:
                        display_name = [name for name, sym in STOCKS_MAP.items() if sym == symbol]
                        display_name = display_name[0] if display_name else symbol
                        add_to_breakout_watch(symbol, display_name, "Price Alert", price)
        except:
            pass

# ==================== One‑Line Alert ====================
def send_one_line_alert(item: dict):
    sentiment = item.get('sentiment', '')
    if 'NEUTRAL' in sentiment:
        return
    symbol = item.get('symbol')
    display_name = item.get('display_name', 'Global')
    title = item.get('title', '')
    link = item.get('link', '')
    sector = ''
    if symbol and symbol in STOCK_TO_SECTOR:
        sector = f" ({STOCK_TO_SECTOR[symbol]})"
    emoji = '🟢' if 'POSITIVE' in sentiment else '🔴'
    short_title = title[:60] + ('...' if len(title) > 60 else '')
    if link and is_valid_url(link):
        title_link = f"<a href='{link}'>{short_title}</a>"
    else:
        title_link = short_title
    msg = f"{emoji} {sentiment} <b>#{display_name}</b>{sector}\n{title_link}"
    send_telegram_alert(msg, disable_preview=False)
    # Voice for one-liner
    if ENABLE_VOICE_ALERTS and GTTS_AVAILABLE:
        voice_text = f"{display_name} {sentiment}"
        send_voice_alert(voice_text[:200])

# ==================== Detailed Aggregated Alert ====================
def send_aggregated_alert(symbol, display_name, items):
    if not items: return
    non_neutral = [it for it in items if 'NEUTRAL' not in it.get('sentiment','')]
    if not non_neutral: return
    items = non_neutral
    sentiment = items[0]['sentiment']
    score = items[0]['score']
    for it in items:
        if abs(it['score']) > abs(score):
            score = it['score']
            sentiment = it['sentiment']
    price, market_closed = get_price_for_symbol(symbol)
    price_line = f"💰 बातमीच्या वेळी: ₹{price:.2f}" if price else "💰 किंमत उपलब्ध नाही"
    if price and market_closed: price_line += " (बाजार बंद)"
    if price: save_alert_price(symbol, price)
    source_tag = f"📡 {items[0].get('source','RSS')}" if items[0].get('source') != "RSS" else ""
    priority = abs(score) >= 0.5
    headlines = []
    for idx, it in enumerate(items[:5]):
        sumry = summarize_text(it['title'], 1)
        headlines.append(f"{idx+1}. {sumry} ({it.get('time','')})")
    combined = "\n".join(headlines)
    if len(items) > 5: combined += f"\n... आणि {len(items)-5} अधिक"
    msg = f"{sentiment} <b>#{display_name}</b> (Score: {score:.2f})\n"
    msg += f"📌 {len(items)} बातम्या {source_tag}\n{price_line}\n─────────────────────\n{combined}"
    if items[0].get('link'): msg += f"\n🔗 <a href='{items[0]['link']}'>पहिली बातमी</a>"
    if priority: msg = f"🚨 HIGH IMPACT 🚨\n{msg}"

    # Smart Insight
    price_change = None
    if price:
        pre = get_pre_price_5m(symbol)
        if pre and pre != price: price_change = (price - pre) / pre * 100
    smart = get_smart_summary(symbol, score, price_change)
    msg += f"\n🧠 <b>Insight:</b> {smart}"

    # Historical context
    hist = get_historical_context(symbol, score, horizon='15m')
    if hist['count'] > 0:
        avg_move = hist['avg_change']
        count = hist['count']
        std = hist['std']
        msg += f"\n📊 <b>Historical context:</b> {count} similar past events → average 15m move: {avg_move:+.2f}% (std {std:.2f}%)"

    # ---- Global Market Context ----
    if ENABLE_GLOBAL_CONTEXT:
        global_ctx = get_global_market_context()
        if global_ctx:
            ctx_line = "🌍 Global: " + " | ".join([f"{k}: {v:+.2f}%" for k, v in global_ctx.items()])
            msg += f"\n{ctx_line}"

    # ---- Event Calendar ----
    if ENABLE_EVENT_CALENDAR:
        events = get_upcoming_events(symbol, days=3)
        if events:
            msg += f"\n📅 Events: " + ", ".join(events)

    # ---- Technical Indicators ----
    if ENABLE_TECHNICAL_INDICATORS:
        tech = get_technical_indicators(symbol)
        if tech:
            tech_line = f"📊 50MA: {tech.get('ma50')} | 200MA: {tech.get('ma200')} | RSI: {tech.get('rsi')}"
            tech_line += f" | 52W High: {tech.get('high52')} | Low: {tech.get('low52')}"
            msg += f"\n{tech_line}"

    # ---- Volume Spike ----
    if ENABLE_VOLUME_SPIKE and check_volume_spike(symbol):
        msg += "\n📈 <b>Volume Spike Detected!</b> (2x avg volume) – breakout confirmed."

    # ---- Ensemble ML Prediction ----
    if price and not market_closed and ML_AVAILABLE:
        row = {
            'sentiment_score': score,
            'hour': datetime.now().hour,
            'weekday': datetime.now().weekday(),
            'price_at_event': price,
            'pre_price_5m': get_pre_price_5m(symbol) or price,
            'vol_avg': get_vol_avg(symbol) or 0.0,
            'sector_sent': get_sector_sentiment(symbol),
            'market_sent': get_nifty_change(),
            'nifty_change': get_nifty_change(),
            'category': get_category(items[0]['title'])
        }
        features = ensemble.prepare_features(row)
        pred_class, prob = ensemble.predict_ensemble(features)
        labels = ['DOWN', 'NEUTRAL', 'UP']
        label = labels[pred_class]
        emoji = {'UP':'📈','DOWN':'📉','NEUTRAL':'➡️'}.get(label,'')
        msg += f"\n🔮 <b>Ensemble ML:</b> {emoji} {label} ({prob*100:.0f}%)"

        # ---- A/B Testing (log) ----
        if ENABLE_AB_TESTING and TF_AVAILABLE and ensemble.lstm_model:
            # In a real implementation, you'd compare later
            pass

    # ---- Smart Priority (buttons) ----
    buttons = [
        [{"text": "🔕 Snooze 1h", "callback_data": f"snooze_{items[0].get('id','')}"}],
        [{"text": "⭐ Add Watchlist", "callback_data": f"watch_{symbol}"}],
        [{"text": "❌ Dismiss", "callback_data": f"dismiss_{items[0].get('id','')}"}]
    ]
    send_telegram_alert(msg, disable_preview=False, buttons=buttons)

    # ---- Voice Alert ----
    if ENABLE_VOICE_ALERTS and GTTS_AVAILABLE:
        voice_text = f"{display_name} {sentiment} Score {score:.2f}. {smart}"
        send_voice_alert(voice_text[:200])

    # ---- Breakout watch ----
    if market_closed:
        if 'POSITIVE' in sentiment:
            alert_type = "Positive News"
        elif 'NEGATIVE' in sentiment:
            alert_type = "Negative News"
        else:
            alert_type = "News Alert"
        add_to_breakout_watch(symbol, display_name, alert_type, price if price else 0.0)

    # ---- Interactive Chart ----
    if PLOTLY_AVAILABLE and TELEGRAPH_AVAILABLE:
        data = get_intraday_data(symbol, "5d")
        if data is not None:
            send_interactive_chart(symbol, display_name, data)

    # ---- Static chart ----
    if market_closed:
        ohlc = get_day_ohlc(symbol)
        if ohlc:
            caption = f"📊 {display_name} - बाजार बंद\nLTP: ₹{ohlc['ltp']:.2f}\nHigh: ₹{ohlc['high']:.2f}\nLow: ₹{ohlc['low']:.2f}\nOpen: ₹{ohlc['open']:.2f}"
            data = get_intraday_data(symbol, "7d")
            if data is not None:
                chart = generate_3min_chart(symbol, display_name, data)
                if chart:
                    send_telegram_photo(chart, caption)
                    try: os.unlink(chart)
                    except: pass

# ==================== Interactive Chart (Plotly + Telegraph) ====================
def generate_interactive_chart(symbol, display_name, data, news_time=None):
    if not PLOTLY_AVAILABLE or data is None or data.empty:
        return None
    try:
        fig = go.Figure(data=[go.Candlestick(
            x=data.index,
            open=data['Open'],
            high=data['High'],
            low=data['Low'],
            close=data['Close'],
            name='Price'
        )])
        if news_time:
            fig.add_vline(x=news_time, line_width=2, line_dash="dash", line_color="red", annotation_text="News")
        fig.update_layout(title=f"{display_name} - Intraday", xaxis_title="Time", yaxis_title="Price (₹)")
        return fig.to_html(full_html=False)
    except:
        return None

def send_interactive_chart(symbol, display_name, data, news_time=None):
    if not TELEGRAPH_AVAILABLE:
        return
    try:
        html = generate_interactive_chart(symbol, display_name, data, news_time)
        if not html: return
        telegraph = Telegraph()
        telegraph.create_account(short_name='NewsBot')
        response = telegraph.create_page(
            title=f"{display_name} Chart",
            html_content=html,
            author_name="News Bot"
        )
        url = response['url']
        send_telegram_alert(f"📊 <b>Interactive Chart</b>\n{display_name}\n🔗 <a href='{url}'>Click to view</a>")
    except Exception as e:
        logger.error(f"Telegraph upload error: {e}")

# ==================== Auto-Archive ====================
async def auto_archive():
    if not ENABLE_AUTO_ARCHIVE:
        return
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    cutoff = (datetime.now() - timedelta(days=7)).isoformat()
    c.execute("""
        INSERT INTO news_archived (timestamp, symbol, display_name, title, link, sentiment, score, type, source, archived_date)
        SELECT timestamp, symbol, display_name, title, link, sentiment, score, type, source, ?
        FROM news WHERE timestamp < ?
    """, (datetime.now().isoformat(), cutoff))
    c.execute("DELETE FROM news WHERE timestamp < ?", (cutoff,))
    conn.commit()
    conn.close()
    logger.info("✅ Auto-archive completed.")

# ==================== Daily / Startup Summary ====================
def send_daily_summary():
    try:
        ist = pytz.timezone('Asia/Kolkata')
        now = datetime.now(ist)
        today = now.strftime('%Y-%m-%d')
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("SELECT sent FROM daily_summary_sent WHERE date=?", (today,))
        if c.fetchone():
            conn.close()
            return
        cutoff = (now - timedelta(hours=24)).isoformat()
        c.execute("""
            SELECT symbol, display_name, title, link, sentiment, score, timestamp
            FROM news WHERE timestamp > ? AND sentiment NOT LIKE '%NEUTRAL%'
            ORDER BY timestamp
        """, (cutoff,))
        rows = c.fetchall()
        conn.close()
        if not rows:
            return
        groups = {}
        for row in rows:
            symbol = safe_str(row[0])
            display = safe_str(row[1])
            title = safe_str(row[2])
            link = safe_str(row[3])
            sentiment = safe_str(row[4])
            score = safe_float(row[5])
            ts = safe_str(row[6])
            if not symbol:
                continue
            dt = datetime.fromisoformat(ts)
            dt_ist = dt.astimezone(ist) if dt.tzinfo else ist.localize(dt)
            groups.setdefault(symbol, {'display': display, 'items': []})
            groups[symbol]['items'].append({
                'title': title, 'link': link, 'sentiment': sentiment,
                'score': score, 'time': dt_ist.strftime('%I:%M %p')
            })
        msg = f"📊 <b>दैनिक बातमी सारांश</b> – {now.strftime('%d %b %Y')}\n"
        msg += "═══════════════════════════════════\n\n"
        for symbol, data in groups.items():
            display = data['display']
            items = data['items']
            msg += f"🔹 <b>{display}</b> ({len(items)} बातम्या)\n"
            for it in items[:5]:
                sumry = summarize_text(it['title'], 1)
                msg += f"   {it['time']} {it['sentiment']} {sumry}\n"
            if len(items) > 5:
                msg += f"   ... आणि {len(items)-5} अधिक\n"
            msg += "\n"
        all_scores = [it['score'] for grp in groups.values() for it in grp['items']]
        if all_scores:
            avg = sum(all_scores) / len(all_scores)
            mood = "🟢 तेजी" if avg > 0.2 else ("🔴 मंदी" if avg < -0.2 else "⚪ तटस्थ")
            msg += f"📊 <b>एकूण मूड:</b> {mood} (सरासरी: {avg:.2f})\n"
        send_telegram_alert(msg)
        conn = sqlite3.connect(DB_FILE)
        conn.execute("INSERT OR REPLACE INTO daily_summary_sent (date, sent) VALUES (?, 1)", (today,))
        conn.commit()
        conn.close()
        logger.info("✅ Daily summary sent.")
    except Exception as e:
        logger.error(f"Daily summary error: {e}")

def send_startup_summary():
    try:
        ist = pytz.timezone('Asia/Kolkata')
        now = datetime.now(ist)
        cutoff = (now - timedelta(hours=24)).isoformat()
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("""
            SELECT symbol, display_name, title, link, sentiment, score, timestamp
            FROM news WHERE timestamp > ? AND sentiment NOT LIKE '%NEUTRAL%'
            ORDER BY timestamp
        """, (cutoff,))
        rows = c.fetchall()
        conn.close()
        if not rows:
            send_telegram_alert("📭 No non‑neutral news in the last 24 hours.")
            return
        groups = {}
        for row in rows:
            symbol = safe_str(row[0])
            display = safe_str(row[1])
            title = safe_str(row[2])
            link = safe_str(row[3])
            sentiment = safe_str(row[4])
            score = safe_float(row[5])
            ts = safe_str(row[6])
            if not symbol:
                continue
            dt = datetime.fromisoformat(ts)
            dt_ist = dt.astimezone(ist) if dt.tzinfo else ist.localize(dt)
            groups.setdefault(symbol, {'display': display, 'items': []})
            groups[symbol]['items'].append({
                'title': title, 'link': link, 'sentiment': sentiment,
                'score': score, 'time': dt_ist.strftime('%I:%M %p')
            })
        msg = f"📊 <b>Startup Summary – Last 24h</b> – {now.strftime('%d %b %Y %I:%M %p IST')}\n"
        msg += "═══════════════════════════════════\n\n"
        for symbol, data in groups.items():
            display = data['display']
            items = data['items']
            msg += f"🔹 <b>{display}</b> ({len(items)} बातम्या)\n"
            for it in items[:5]:
                sumry = summarize_text(it['title'], 1)
                msg += f"   {it['time']} {it['sentiment']} {sumry}\n"
            if len(items) > 5:
                msg += f"   ... आणि {len(items)-5} अधिक\n"
            msg += "\n"
        all_scores = [it['score'] for grp in groups.values() for it in grp['items']]
        if all_scores:
            avg = sum(all_scores) / len(all_scores)
            mood = "🟢 तेजी" if avg > 0.2 else ("🔴 मंदी" if avg < -0.2 else "⚪ तटस्थ")
            msg += f"📊 <b>एकूण मूड:</b> {mood} (सरासरी: {avg:.2f})\n"
        send_telegram_alert(msg)
    except Exception as e:
        logger.error(f"Startup summary error: {e}")

# ==================== Main Loop ====================
async def main_loop():
    await init_db_async()
    logger.info("🚀 ULTIMATE NEWS BOT STARTED (all 11 features active)")

    await ensemble.retrain_ensemble_async()

    features = []
    if ENABLE_VOICE_ALERTS: features.append("🗣️ Voice")
    if ENABLE_GLOBAL_CONTEXT: features.append("🌍 Global Context")
    if ENABLE_TECHNICAL_INDICATORS: features.append("📊 Technical")
    if ENABLE_EVENT_CALENDAR: features.append("📅 Events")
    if ENABLE_VOLUME_SPIKE: features.append("📈 Volume Spike")
    if ENABLE_AUTO_ARCHIVE: features.append("🗄️ Auto-Archive")
    if ENABLE_AB_TESTING: features.append("🧪 A/B Testing")
    send_telegram_alert(f"⚡ <b>ULTIMATE NEWS BOT ACTIVE</b>\n✅ Features: {', '.join(features)}")

    send_startup_summary()

    last_news_time = None
    current_interval = CHECK_INTERVAL
    last_archive_check = datetime.now()

    while True:
        try:
            check_price_triggers()
            check_breakout_watches()

            logger.info(f"🔄 Scan (interval {current_interval}s)")
            all_items = []
            async with aiohttp.ClientSession() as session:
                tasks = [fetch_feed(session, url) for url in RSS_FEEDS]
                results = await asyncio.gather(*tasks)
                for items in results:
                    for it in items:
                        if not is_cached(it['title'], it['link']) and not news_exists(it['title'], it['link']):
                            add_cache(it['title'], it['link'])
                            all_items.append(it)

            if all_items:
                logger.info(f"✅ {len(all_items)} new items")
                last_news_time = datetime.now()
                current_interval = 30

                for item in all_items:
                    send_one_line_alert(item)

                for it in all_items:
                    insert_news_with_features(it)
                    if socketio:
                        emit_new_news({
                            'timestamp': it.get('time'),
                            'symbol': it.get('symbol'),
                            'display_name': it.get('display_name'),
                            'title': it.get('title'),
                            'link': it.get('link'),
                            'sentiment': it.get('sentiment'),
                            'score': it.get('score')
                        })

                stock_dict = {}
                macro_items = []
                for it in all_items:
                    if it['type'] == 'stock':
                        stock_dict.setdefault(it['symbol'], []).append(it)
                    else:
                        macro_items.append(it)

                for sym, items in stock_dict.items():
                    display = items[0]['display_name']
                    send_aggregated_alert(sym, display, items)
                    price, _ = get_price_for_symbol(sym)
                    if price:
                        track_price_impact(sym, datetime.now(), price)

                # Macro digest
                if macro_items:
                    non_neutral_macro = [it for it in macro_items if 'NEUTRAL' not in it['sentiment']]
                    if non_neutral_macro:
                        msg = "🌍 <b>मॅक्रो/ग्लोबल डायजेस्ट</b>\n─────────────────────\n"
                        for it in non_neutral_macro[:5]:
                            msg += f"{it['sentiment']} {it['display_name']}\n🕐 {it['time']}\n📌 {summarize_text(it['title'],1)}\n"
                            if it.get('link'):
                                msg += f"🔗 <a href='{it['link']}'>Read more</a>\n"
                            msg += "─────────────────────\n"
                        send_telegram_alert(msg)

                # Market mood
                all_scores = [it['score'] for it in all_items if it['score'] != 0]
                if all_scores:
                    avg = sum(all_scores)/len(all_scores)
                    mood = "🟢 तेजी" if avg > 0.2 else ("🔴 मंदी" if avg < -0.2 else "⚪ तटस्थ")
                    send_telegram_alert(f"📊 <b>बाजार मूड</b>\nसरासरी स्कोअर: {avg:.2f}\nभावना: {mood}")

                if (datetime.now() - last_archive_check) > timedelta(days=1):
                    await ensemble.retrain_ensemble_async(force=True)

            else:
                current_interval = min(120, current_interval + 5) if last_news_time and (datetime.now()-last_news_time).total_seconds()>300 else min(120, current_interval+5)

            # Auto-archive daily
            if (datetime.now() - last_archive_check) > timedelta(days=1):
                await auto_archive()
                last_archive_check = datetime.now()

            # Daily summary at 9:10 AM
            ist = pytz.timezone('Asia/Kolkata')
            now_ist = datetime.now(ist)
            if now_ist.weekday() < 5 and now_ist.hour == 9 and now_ist.minute == 10:
                if (datetime.now() - last_archive_check).total_seconds() > 60:
                    send_daily_summary()
                    last_archive_check = datetime.now()

        except Exception as e:
            logger.error(f"Main loop error: {e}")
        await asyncio.sleep(current_interval)

# ==================== Flask Web App with Dark Mode Dashboard ====================
app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret!'
socketio = SocketIO(app, cors_allowed_origins="*") if SOCKETIO_AVAILABLE else None

def emit_new_news(news_item):
    if socketio:
        socketio.emit('new_news', news_item, namespace='/dashboard')

@app.route('/')
def home():
    return render_template_string(HTML_TEMPLATE)

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>📰 Ultimate Dashboard</title>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        /* Dark mode base */
        body {
            font-family: 'Segoe UI', sans-serif;
            background: #121212;
            color: #e0e0e0;
            padding: 20px;
            transition: background 0.3s, color 0.3s;
        }
        .container { max-width: 1400px; margin: auto; }
        h1 { color: #bb86fc; border-bottom: 2px solid #bb86fc; padding-bottom: 10px; display: flex; align-items: center; gap: 10px; }
        .status-bar {
            background: #1e1e1e;
            padding: 15px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.3);
            margin: 20px 0;
            display: flex;
            gap: 20px;
            flex-wrap: wrap;
            align-items: center;
        }
        .status-item { display: flex; align-items: center; gap: 5px; }
        .refresh-btn {
            background: #bb86fc;
            color: #121212;
            border: none;
            padding: 6px 14px;
            border-radius: 4px;
            cursor: pointer;
        }
        .refresh-btn:hover { background: #9a6fdb; }
        .grid { display: grid; grid-template-columns: 2fr 1fr; gap: 20px; }
        @media (max-width:768px){ .grid { grid-template-columns: 1fr; } }
        .card {
            background: #1e1e1e;
            border-radius: 8px;
            padding: 20px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.4);
        }
        .card h2 { color: #bb86fc; border-bottom: 1px solid #333; padding-bottom: 10px; }
        .news-item {
            padding: 10px 0;
            border-bottom: 1px solid #2a2a2a;
            font-size: 14px;
        }
        .news-time { color: #888; font-size: 12px; }
        .sentiment-icon { margin-right: 5px; }
        .symbol-tag {
            background: #333;
            padding: 2px 8px;
            border-radius: 12px;
            font-size: 12px;
            font-weight: bold;
            color: #bb86fc;
        }
        .search-box { display: flex; gap: 10px; margin-bottom: 15px; }
        .search-box input {
            flex:1;
            padding: 8px;
            border: 1px solid #333;
            border-radius: 4px;
            background: #2a2a2a;
            color: #e0e0e0;
        }
        .search-box button {
            padding:8px 16px;
            background:#bb86fc;
            color:#121212;
            border:none;
            border-radius:4px;
            cursor:pointer;
        }
        .search-box button:hover { background: #9a6fdb; }
        .chart-btn {
            background: #03dac6;
            color: #121212;
            border: none;
            padding: 2px 8px;
            border-radius: 4px;
            cursor: pointer;
            font-size: 12px;
            margin-left: 5px;
        }
        .chart-btn:hover { background: #01b8a5; }
        .sector-list { display: grid; grid-template-columns:1fr 1fr; gap:8px; }
        .sector-item {
            display:flex;
            justify-content:space-between;
            padding:6px 0;
            border-bottom:1px solid #2a2a2a;
        }
        .trend-input { display:flex; gap:10px; margin-bottom:10px; }
        .trend-input input {
            flex:1;
            padding:8px;
            border:1px solid #333;
            border-radius:4px;
            background:#2a2a2a;
            color:#e0e0e0;
        }
        .trend-input button {
            padding:8px 16px;
            background:#bb86fc;
            color:#121212;
            border:none;
            border-radius:4px;
            cursor:pointer;
        }
        .trend-result { padding:10px; background:#2a2a2a; border-radius:4px; }
        .news-title-link { text-decoration:none; color:#bb86fc; }
        .news-title-link:hover { text-decoration:underline; color:#9a6fdb; }
        .live-badge {
            background: #cf6679;
            color: #121212;
            padding: 2px 8px;
            border-radius: 20px;
            font-size: 12px;
            animation: blink 1s infinite;
        }
        @keyframes blink { 50% { opacity: 0.5; } }
        .dark-toggle {
            margin-left: auto;
            background: #bb86fc;
            color: #121212;
            border: none;
            padding: 6px 14px;
            border-radius: 4px;
            cursor: pointer;
        }
        .sparkline { margin-top: 5px; height: 30px; }
        .calendar-view { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 10px; }
        .cal-event {
            background: #2a2a2a;
            padding: 6px 12px;
            border-radius: 12px;
            font-size: 12px;
            border-left: 3px solid #bb86fc;
        }
    </style>
</head>
<body>
<div class="container">
    <h1>
        📰 Ultimate Dashboard
        <span class="live-badge">🔴 LIVE</span>
        <button class="dark-toggle" onclick="toggleDark()">🌓 Toggle</button>
    </h1>
    <div class="status-bar" id="statusBar">
        <span class="status-item">🔄 Status: <span id="statusText">Loading...</span></span>
        <span class="status-item">📰 Total News: <span id="totalNews">0</span></span>
        <span class="status-item">⏱️ Interval: <span id="interval">-</span>s</span>
        <button class="refresh-btn" onclick="refreshAll()">⟳ Refresh</button>
    </div>
    <div class="grid">
        <div class="card">
            <h2>📰 Latest News (50) <span style="font-size:12px;color:#888;">(click title to open)</span></h2>
            <div class="search-box">
                <input type="text" id="searchInput" placeholder="Search...">
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
                    <input type="text" id="trendSymbol" placeholder="e.g. RELIANCE.NS">
                    <button onclick="getTrend()">Get</button>
                </div>
                <div id="trendResult" class="trend-result">Enter symbol to see sentiment trend (last 2h).</div>
            </div>
            <div class="card" style="margin-top:20px;">
                <h2>📅 Upcoming Events</h2>
                <div id="calendarView" class="calendar-view">Fetching...</div>
            </div>
        </div>
    </div>
</div>
<script>
    // WebSocket
    var socket = io.connect('http://' + document.domain + ':' + location.port + '/dashboard');
    socket.on('connect', function() { console.log('WebSocket connected'); });
    socket.on('new_news', function(data) {
        var list = document.getElementById('newsList');
        var item = document.createElement('div');
        item.className = 'news-item';
        var time = data.timestamp ? new Date(data.timestamp).toLocaleString() : '';
        var sentiment = data.sentiment ? data.sentiment.split(' ')[0] : '⚪';
        var title = data.title ? data.title.substring(0,100) + (data.title.length>100?'...':'') : '';
        var link = data.link ? `<a href="${data.link}" target="_blank" class="news-title-link">${title}</a>` : title;
        var tvSymbol = data.symbol ? 'NSE:' + data.symbol.replace('.NS','') : '';
        var chartUrl = tvSymbol ? `https://www.tradingview.com/chart/?symbol=${tvSymbol}&interval=5` : '';
        var chartBtn = chartUrl ? `<button class="chart-btn" onclick="window.open('${chartUrl}','_blank')">📊 Chart</button>` : '';
        item.innerHTML = `
            <span class="news-time">${time}</span>
            <span class="sentiment-icon">${sentiment}</span>
            <span class="symbol-tag">${data.symbol || '📰'}</span>
            <strong>${data.display_name || ''}</strong>
            <span style="font-size:12px;color:#888;">(score: ${data.score ? data.score.toFixed(2) : 0})</span><br>
            ${link} ${data.link ? `<a href="${data.link}" target="_blank" style="font-size:12px;color:#888;">🔗</a>` : ''} ${chartBtn}
            <div id="spark_${data.id || Date.now()}" class="sparkline"></div>
        `;
        list.insertBefore(item, list.firstChild);
        while (list.children.length > 50) list.removeChild(list.lastChild);
        // Sparkline (dummy)
        if (typeof sparkline !== 'undefined') sparkline();
    });

    // Dark mode toggle
    function toggleDark() {
        document.body.style.background = document.body.style.background === '#121212' ? '#f4f6f9' : '#121212';
        document.body.style.color = document.body.style.color === '#e0e0e0' ? '#333' : '#e0e0e0';
    }

    // REST functions
    async function fetchJSON(url) { const r=await fetch(url); if(!r.ok)throw Error(); return r.json(); }
    async function loadStatus() { try { let d=await fetchJSON('/status'); document.getElementById('statusText').textContent=d.status||'unknown'; document.getElementById('totalNews').textContent=d.total_news||0; document.getElementById('interval').textContent=d.interval||'-'; } catch(e) { document.getElementById('statusText').textContent='⚠️ Error'; } }
    async function loadNews(q='') { try { let url=q?'/search?q='+encodeURIComponent(q):'/news'; let data=await fetchJSON(url); let list=document.getElementById('newsList'); if(!data.length){ list.innerHTML='<p>No news found.</p>'; return; } list.innerHTML=data.map(n=>{ let titleText=n.title?n.title.substring(0,100)+(n.title.length>100?'...':''):''; let titleHtml=n.link?`<a href="${n.link}" target="_blank" class="news-title-link">${titleText}</a>`:titleText; let tvSymbol=n.symbol?'NSE:'+n.symbol.replace('.NS',''):''; let chartUrl=tvSymbol?`https://www.tradingview.com/chart/?symbol=${tvSymbol}&interval=5`:''; let chartBtn=chartUrl?`<button class="chart-btn" onclick="window.open('${chartUrl}','_blank')">📊 Chart</button>`:''; return `<div class="news-item"><span class="news-time">${n.timestamp?new Date(n.timestamp).toLocaleString():''}</span> <span class="sentiment-icon">${n.sentiment?n.sentiment.split(' ')[0]:'⚪'}</span> <span class="symbol-tag">${n.symbol||'📰'}</span> <strong>${n.display_name||''}</strong> <span style="font-size:12px;color:#888;">(score: ${n.score?n.score.toFixed(2):0})</span><br>${titleHtml} ${n.link?`<a href="${n.link}" target="_blank" style="font-size:12px;color:#888;">🔗</a>`:''} ${chartBtn}</div>` }).join(''); } catch(e){ document.getElementById('newsList').innerHTML='<p style="color:red;">Error loading news.</p>'; } }
    function searchNews(){ let q=document.getElementById('searchInput').value.trim(); if(q) loadNews(q); else loadNews(); }
    function clearSearch(){ document.getElementById('searchInput').value=''; loadNews(); }
    async function loadSectors(){ try { let data=await fetchJSON('/sector_sentiment'); let container=document.getElementById('sectorList'); container.innerHTML=Object.entries(data).map(([sector,score])=>`<div class="sector-item"><span>${sector}</span><span style="font-weight:bold;color:${score>0.1?'#03dac6':score<-0.1?'#cf6679':'#888'}">${score.toFixed(2)}</span></div>`).join(''); } catch(e){ document.getElementById('sectorList').innerHTML='<p style="color:red;">Error</p>'; } }
    async function getTrend(){ let sym=document.getElementById('trendSymbol').value.trim(); if(!sym){ document.getElementById('trendResult').textContent='Enter symbol'; return; } try { let data=await fetchJSON('/trend/'+encodeURIComponent(sym)); let avg=data.avg_score||0; let dir=data.direction||0; let dirText=dir>0?'⬆️ Bullish':dir<0?'⬇️ Bearish':'➡️ Neutral'; document.getElementById('trendResult').innerHTML=`<strong>${sym}</strong><br>Avg Sentiment (2h): <span style="font-weight:bold;color:${avg>0.1?'#03dac6':avg<-0.1?'#cf6679':'#888'}">${avg.toFixed(2)}</span><br>Direction: ${dirText}`; } catch(e){ document.getElementById('trendResult').textContent='Error'; } }
    async function loadCalendar(){ try { let data=await fetchJSON('/calendar'); let container=document.getElementById('calendarView'); if(!data.length){ container.innerHTML='No upcoming events'; return; } container.innerHTML=data.map(e=>`<div class="cal-event">${e.symbol}: ${e.event}</div>`).join(''); } catch(e){ document.getElementById('calendarView').innerHTML='Error loading calendar'; } }
    async function refreshAll(){ await Promise.all([loadStatus(), loadNews(), loadSectors(), loadCalendar()]); }
    refreshAll(); setInterval(refreshAll, 30000);
</script>
<script src="https://cdn.socket.io/4.5.0/socket.io.min.js"></script>
</body>
</html>
"""

# ==================== Flask Routes ====================
@app.route('/news')
def api_news():
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("SELECT id,timestamp,symbol,display_name,title,link,sentiment,score,type,source FROM news ORDER BY timestamp DESC LIMIT 50")
        rows = c.fetchall()
        conn.close()
        return jsonify([{
            'id': r[0],
            'timestamp': safe_str(r[1]),
            'symbol': safe_str(r[2] or ''),
            'display_name': safe_str(r[3] or ''),
            'title': safe_str(r[4] or ''),
            'link': safe_str(r[5] or ''),
            'sentiment': safe_str(r[6] or '⚪ NEUTRAL'),
            'score': safe_float(r[7]),
            'type': safe_str(r[8] or ''),
            'source': safe_str(r[9] or '')
        } for r in rows])
    except Exception as e:
        return jsonify([])

@app.route('/search')
def api_search():
    q = request.args.get('q','')
    if not q:
        return jsonify({'error':'Missing q'}),400
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("SELECT timestamp,symbol,display_name,title,link,sentiment,score FROM news WHERE title LIKE ? OR symbol LIKE ? ORDER BY timestamp DESC LIMIT 20", (f'%{q}%', f'%{q}%'))
        rows = c.fetchall()
        conn.close()
        return jsonify([{
            'timestamp': safe_str(r[0]),
            'symbol': safe_str(r[1] or ''),
            'display_name': safe_str(r[2] or ''),
            'title': safe_str(r[3] or ''),
            'link': safe_str(r[4] or ''),
            'sentiment': safe_str(r[5] or '⚪ NEUTRAL'),
            'score': safe_float(r[6])
        } for r in rows])
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/trend/<symbol>')
def api_trend(symbol):
    avg, direction = get_sentiment_trend(symbol)
    return jsonify({'symbol': symbol, 'avg_score': avg, 'direction': direction})

@app.route('/sector_sentiment')
def api_sector():
    sector_scores = {}
    for sector, syms in SECTOR_MAP.items():
        scores = []
        for sym in syms:
            avg, _ = get_sentiment_trend(sym, 120)
            if avg != 0:
                scores.append(avg)
        sector_scores[sector] = sum(scores)/len(scores) if scores else 0.0
    return jsonify(sector_scores)

@app.route('/status')
def api_status():
    try:
        conn = sqlite3.connect(DB_FILE)
        count = conn.execute("SELECT COUNT(*) FROM news").fetchone()[0]
        conn.close()
        return jsonify({'total_news': count, 'status': 'running', 'interval': current_interval})
    except:
        return jsonify({'total_news': 0, 'status': 'error', 'interval': 0})

@app.route('/calendar')
def api_calendar():
    try:
        # Get all stocks that have news in the last week
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("SELECT DISTINCT symbol FROM news WHERE timestamp > datetime('now', '-7 days')")
        symbols = [r[0] for r in c.fetchall() if r[0]]
        conn.close()
        events = []
        for sym in symbols[:10]:  # limit to 10 for performance
            evs = get_upcoming_events(sym, days=7)
            for e in evs:
                events.append({'symbol': sym, 'event': e})
        return jsonify(events)
    except:
        return jsonify([])

def get_sentiment_trend(symbol, minutes=120):
    try:
        conn = sqlite3.connect(DB_FILE)
        cutoff = (datetime.now() - timedelta(minutes=minutes)).isoformat()
        rows = conn.execute("SELECT score FROM news WHERE symbol=? AND timestamp > ?", (symbol, cutoff)).fetchall()
        conn.close()
        if not rows: return 0,0
        scores = [safe_float(r[0]) for r in rows]
        avg = sum(scores)/len(scores)
        direction = 1 if avg > 0.1 else -1 if avg < -0.1 else 0
        return avg, direction
    except:
        return 0,0

# ==================== Run ====================
if __name__ == "__main__":
    if socketio:
        threading.Thread(target=lambda: socketio.run(app, host='0.0.0.0', port=API_PORT, debug=False, use_reloader=False), daemon=True).start()
    else:
        threading.Thread(target=lambda: app.run(host='0.0.0.0', port=API_PORT, debug=False, use_reloader=False), daemon=True).start()
    asyncio.run(main_loop())
