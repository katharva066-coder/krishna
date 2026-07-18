import yfinance as yf
import requests
from bs4 import BeautifulSoup
import time
import os
import threading
from datetime import datetime
from flask import Flask  # फ्री क्लाउडवर जिवंत राहण्यासाठी

# ==================== CONFIGURATION ====================
TELEGRAM_BOT_TOKEN = "8634800722:AAESXRx8Xx3i1mqQvJCsh8ecLd0eP3kPdJQ"
TELEGRAM_CHAT_ID = "1106122116"
CHECK_INTERVAL = 60
# =======================================================

# ---- FLASK WEB SERVER (जुगाड सिस्टीम) ----
flask_app = Flask('')

@flask_app.route('/')
def home():
    return "⚡ Shambhu's Radar Bot is Active & Running 24/7! ⚡"

def run_server():
    # Render कडून मिळणारा पोर्ट ऑटोमॅटिक डिटेक्ट करणे
    port = int(os.environ.get("PORT", 8080))
    flask_app.run(host='0.0.0.0', port=port)
# ------------------------------------------

def get_index_data(ticker):
    try:
        ticker_obj = yf.Ticker(ticker)
        todays_data = ticker_obj.history(period="2d")
        if len(todays_data) >= 1:
            latest_price = todays_data['Close'].iloc[-1]
            if len(todays_data) >= 2:
                prev_close = todays_data['Close'].iloc[-2]
            else:
                prev_close = todays_data['Open'].iloc[-1]
            pct_change = ((latest_price - prev_close) / prev_close) * 100
            return round(latest_price, 2), round(pct_change, 2)
    except Exception as e:
        print(f"Error fetching ticker {ticker}: {e}")
    return "N/A", 0.0

def get_zerodha_pulse_live_news():
    url = "https://pulse.zerodha.com/"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Referer": "https://www.google.com/"
    }
    pos_words = ['bull', 'bullish', 'surge', 'gain', 'rise', 'rally', 'positive', 'growth', 'jump', 'upward', 'soar', 'profit', 'high', 'up']
    neg_words = ['bear', 'bearish', 'crash', 'fall', 'drop', 'slump', 'negative', 'loss', 'down', 'sink', 'plunge', 'worry', 'fear', 'risk']
    news_list, news_score = [], 0
    try:
        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            links = soup.find_all('a')
            count = 0
            for link in links:
                title_text = link.get_text().strip()
                href = link.get('href', '')
                if len(title_text) > 25 and href:
                    if href.startswith('/'):
                        href = "https://pulse.zerodha.com" + href
                    clean_title = title_text.replace("[", "").replace("]", "").replace("(", "").replace(")", "")
                    if (clean_title, href) not in news_list:
                        news_list.append((clean_title, href))
                        count += 1
                        title_lower = clean_title.lower()
                        for word in pos_words:
                            if word in title_lower: news_score += 1
                        for word in neg_words:
                            if word in title_lower: news_score -= 1
                if count >= 5:
                    break
    except Exception as e:
        print(f"BeautifulSoup Scraper Error: {e}")
    return news_list, news_score

def calculate_final_sentiment(nifty_chg, bank_chg, it_chg, vix_chg, news_score):
    bullish_points = 0
    bearish_points = 0
    if nifty_chg > 0: bullish_points += 2
    else: bearish_points += 2
    if bank_chg > 0: bullish_points += 1.5
    else: bearish_points += 1.5
    if it_chg > 0: bullish_points += 1
    else: bearish_points += 1
    if vix_chg < 0: bullish_points += 2
    else: bearish_points += 2
    if news_score > 0: bullish_points += 2
    elif news_score < 0: bearish_points += 2
    
    if bullish_points > bearish_points + 1.5:
        return "🔥 STRONGLY BULLISH", "मार्केटमध्ये जोरदार खरेदीचा मूड दिसत आहे. बुल्स पूर्णपणे Control मध्ये आहेत."
    elif bullish_points > bearish_points:
        return "📈 MILDLY BULLISH", "मार्केटमध्ये पॉझिटिव्ह मोमेंटम आहे, पण सावध राहून ट्रेड करा."
    elif bearish_points > bullish_points + 1.5:
        return "🚨 STRONGLY BEARISH", "मार्केटमध्ये भीतीचे वातावरण आहे, शॉर्ट साईडला किंवा पुट (PUT) साईडला मोमेंटम मिळू शकतो."
    elif bearish_points > bullish_points:
        return "📉 MILDLY BEARISH", "मार्केटवर हलका दबाव दिसत आहे. प्रॉफिट बुकिंग चालू असण्याची शक्यता."
    else:
        return "⚖️ NEUTRAL", "मार्केट एका रेंजमध्ये अडकले आहे (Sideways). ब्रेकआऊटची वाट पहा."

def send_telegram_report(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown", "disable_web_page_preview": True}
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print(f"Telegram API Error: {e}")

def main_job():
    nifty_price, nifty_chg = get_index_data("^NSEI")
    bank_price, bank_chg = get_index_data("^NSEBANK")
    it_price, it_chg = get_index_data("^CNXIT")
    vix_price, vix_chg = get_index_data("^INDIAVIX")
    sensex_price, sensex_chg = get_index_data("^BSESN") 
    
    news_items, news_score = get_zerodha_pulse_live_news()
    verdict_title, verdict_desc = calculate_final_sentiment(nifty_chg, bank_chg, it_chg, vix_chg, news_score)
    
    n_emoji = "🟢" if nifty_chg >= 0 else "🔴"
    b_emoji = "🟢" if bank_chg >= 0 else "🔴"
    i_emoji = "🟢" if it_chg >= 0 else "🔴"
    s_emoji = "🟢" if sensex_chg >= 0 else "🔴"
    v_emoji = "🔴" if vix_chg >= 0 else "🟢" 
    
    msg = f" ⚡ *MARKET SENTIMENT RADAR REPORT* ⚡\n"
    msg += f"───────────────────────\n"
    msg += f"🕒 *Time:* {datetime.now().strftime('%I:%M %p')}  |  📅 *Date:* {datetime.now().strftime('%d-%b-%Y')}\n"
    msg += f"───────────────────────\n\n"
    msg += f"📊 *MAJOR INDICES SCORECARD:* 📊\n"
    msg += f"🔹 {n_emoji} *NIFTY 50:*  {nifty_price}  ({nifty_chg}%)\n"
    msg += f"🔹 {b_emoji} *BANK NIFTY:* {bank_price}  ({bank_chg}%)\n"
    msg += f"🔹 {s_emoji} *SENSEX:*     {sensex_price}  ({sensex_chg}%)\n"
    msg += f"🔹 {i_emoji} *NIFTY IT:*   {it_price}  ({it_chg}%)\n"
    msg += f"🔹 {v_emoji} *INDIA VIX:*  {vix_price}  ({vix_chg}%)  `[Fear Index]`\n\n"
    msg += f"📡 *ZERODHA PULSE HOT CUES (Clickable):* 📡\n"
    if news_items:
        for i, (head_title, head_link) in enumerate(news_items, 1):
            msg += f"📌 {i}. [{head_title}]({head_link})\n"
    else:
        msg += f"⚠️ _Zerodha Pulse साईटवरून सध्या डेटा वाचता आला नाही._\n"
    
    sentiment_trend_emoji = "🟢 Positive" if news_score > 0 else "🔴 Negative" if news_score < 0 else "🟡 Neutral"
    msg += f"\n🧠 *Pulse News Trend:*  {sentiment_trend_emoji}\n"
    msg += f"───────────────────────\n\n"
    msg += f"🎯 *FINAL SENTIMENT VERDICT:* ⭐\n"
    msg += f"⚡ *{verdict_title}*\n"
    msg += f"💡 *ॲनालिसिस:* _{verdict_desc}_\n\n"
    msg += f"━━━━━━━━━━━━━━━━━━━━━━━\n"
    msg += f"📢  _⚠️ हा रिपोर्ट फक्त शैक्षणिक हेतूने कोडिंगद्वारे जनरेट केला आहे._"
    
    send_telegram_report(msg)

if __name__ == "__main__":
    print("🚀 Cloud Web-Server बोट सुरू होत आहे...")
    
    # Flask सर्व्हरला दुसऱ्या बॅकग्राउंड थ्रेडवर सुरू करणे
    t = threading.Thread(target=run_server)
    t.daemon = True
    t.start()
    
    main_job()
    initial_news, _ = get_zerodha_pulse_live_news()
    last_top_link = initial_news[0][1] if initial_news else None
    
    while True:
        try:
            time.sleep(CHECK_INTERVAL)
            current_news, _ = get_zerodha_pulse_live_news()
            if current_news:
                current_top_link = current_news[0][1]
                if current_top_link != last_top_link:
                    main_job()
                    last_top_link = current_top_link
        except Exception as e:
            time.sleep(10)