import os
import re
import threading
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from bs4 import BeautifulSoup
from flask import Flask
import requests

# ==================== CONFIGURATION ====================
TELEGRAM_BOT_TOKEN = "8634800722:AAESXRx8Xx3i1mqQvJCsh8ecLd0eP3kPdJQ"
TELEGRAM_CHAT_ID = "1106122116"
CHECK_INTERVAL = 30  # दर ३० सेकंदाला सर्व ७ सोर्सेस स्कॅन करेल
MAX_NEWS_AGE_MINUTES = (
    30  # फक्त गेल्या ३० मिनिटांत पब्लिश झालेल्या बातम्याच पाठवेल
)
# =======================================================

# ---- FLASK WEB SERVER (Render 24/7 साठी) ----
flask_app = Flask("")


@flask_app.route("/")
def home():
  return (
      "⚡ Shambhu's Live Market Radar (9:00 AM & 3:30 PM Reports Active)! ⚡"
  )


def run_server():
  port = int(os.environ.get("PORT", 8080))
  flask_app.run(host="0.0.0.0", port=port)


# ----------------------------------------------

# Search Terms
GLOBAL_QUERY_EXT = (
    'OR "crude oil" OR trump OR fed OR opec OR "us market" OR tariff OR'
    " inflation"
)

SOURCES_CONFIG = [
    {
        "name": "🟢 Moneycontrol",
        "query": (
            f"site:moneycontrol.com (stocks OR market OR nifty OR sensex"
            f" {GLOBAL_QUERY_EXT})"
        ),
    },
    {
        "name": "🟧 Economic Times",
        "query": (
            f"site:economictimes.indiatimes.com (markets OR stocks OR nifty"
            f" {GLOBAL_QUERY_EXT})"
        ),
    },
    {
        "name": "🟦 LiveMint",
        "query": (
            f"site:livemint.com (market OR stocks OR nifty OR sensex"
            f" {GLOBAL_QUERY_EXT})"
        ),
    },
    {
        "name": "🟥 Business Standard",
        "query": (
            f"site:business-standard.com (markets OR stocks OR company"
            f" {GLOBAL_QUERY_EXT})"
        ),
    },
    {
        "name": "🟨 CNBC-TV18",
        "query": (
            f"site:cnbctv18.com (market OR stocks OR business"
            f" {GLOBAL_QUERY_EXT})"
        ),
    },
    {
        "name": "🏛️ NSE Announcements",
        "query": "site:nseindia.com (announcement OR corporate OR filing)",
    },
    {
        "name": "🏛️ BSE Announcements",
        "query": "site:bseindia.com (announcement OR corporate OR filing)",
    },
]

seen_news_titles = set()
daily_stocks_log = []  # ९ AM आणि ३:३० PM च्या रिपोर्टसाठी डेटा साठवणे
has_sent_9am_report = False
has_sent_330pm_report = False


def is_live_market_time():
  """फक्त लाईव्ह मार्केट वेळ (सोमवार ते शुक्रवार, 09:15 AM ते 03:30 PM IST) तपासणे."""
  now = datetime.now()

  # सोमवार (0) ते शुक्रवार (4). ६ आणि ७ (शनिवार, रविवार) बंद.
  if now.weekday() >= 5:
    return False

  market_start = now.replace(hour=9, minute=15, second=0, microsecond=0)
  market_end = now.replace(hour=15, minute=30, second=0, microsecond=0)

  return market_start <= now <= market_end


def get_clean_title(raw_title):
  """टाइटल मधील अक्षरे स्वच्छ करणे."""
  clean = re.sub(r"[^\w\s]", "", raw_title.lower())
  return clean.strip()


def extract_stock_name(title):
  """बातमीच्या Heading मधून कंपनी किंवा स्टॉकचे नाव शोधणे."""
  words = title.split("-")[0].split(":")[0].strip()

  action_keywords = [
      "shares",
      "stock",
      "rallies",
      "surges",
      "drops",
      "falls",
      "bags",
      "signs",
      "q1",
      "q2",
      "q3",
      "q4",
      "profit",
      "loss",
      "target",
  ]
  parts = words.split()

  clean_name = []
  for w in parts:
    if w.lower() in action_keywords:
      break
    clean_name.append(w)

  extracted = " ".join(clean_name).strip()
  if len(extracted) > 2 and len(extracted) < 25:
    return extracted
  return title[:20] + "..."


def analyze_sentiment(title):
  """सेंटीमेंट (Bullish, Bearish, Neutral) ओळखणे."""
  t = title.lower()

  bullish_kw = [
      "surge",
      "jump",
      "rally",
      "gain",
      "profit",
      "up",
      "growth",
      "deal",
      "order",
      "record",
      "high",
      "dividend",
      "bonus",
      "buy",
      "win",
      "expansion",
      "beat",
      "soar",
      "rallies",
      "rate cut",
      "eases",
      "cools",
      "cooling",
      "stimulus",
      "positive",
  ]

  bearish_kw = [
      "plunge",
      "drop",
      "fall",
      "loss",
      "down",
      "slump",
      "decline",
      "crash",
      "cut",
      "fine",
      "penalty",
      "downgrade",
      "miss",
      "resign",
      "low",
      "tumble",
      "probe",
      "rate hike",
      "tariff",
      "sanction",
      "war",
      "conflict",
      "inflation surge",
      "oil rises",
      "crude jumps",
  ]

  bull_score = sum(1 for k in bullish_kw if k in t)
  bear_score = sum(1 for k in bearish_kw if k in t)

  if bull_score > bear_score:
    return "🟢 BULLISH (सकारात्मक)"
  elif bear_score > bull_score:
    return "🔴 BEARISH (नकारात्मक)"
  else:
    return "⚪ NEUTRAL"


def get_news_category(title):
  """बातमीची Category ओळखणे."""
  title_lower = title.lower()

  if any(
      k in title_lower
      for k in ["bse", "nse", "announcement", "circular", "filing"]
  ):
    return "🏛️ CORPORATE FILING"

  global_keywords = [
      "dow",
      "nasdaq",
      "fed",
      "global",
      "us market",
      "asia",
      "wall street",
      "crude oil",
      "crude",
      "oil",
      "dollar",
      "sgx nifty",
      "gift nifty",
      "trump",
      "opec",
      "tariff",
      "china",
      "biden",
      "us inflation",
      "geopolitical",
  ]
  if any(k in title_lower for k in global_keywords):
    return "🌏 GLOBAL & MACRO CUES"

  stock_keywords = [
      "shares",
      "stock",
      "buy",
      "sell",
      "target",
      "profit",
      "revenue",
      "q1",
      "q2",
      "q3",
      "q4",
      "results",
      "order",
      "deal",
      "dividend",
      "bonus",
      "split",
      "acquisition",
      "stake",
  ]
  if any(k in title_lower for k in stock_keywords):
    return "📈 STOCKS IN ACTION"

  return "🇮🇳 INDIAN MARKET SENTIMENT"


def fetch_news_for_source(source_info):
  """प्रत्येक सोर्स स्वतंत्रपणे स्कॅन करणे (फक्त १ तासाच्या आतील बातम्या)."""
  url = f"https://news.google.com/rss/search?q={source_info['query']}+when:1h&hl=en-IN&gl=IN&ceid=IN:en"
  headers = {
      "User-Agent": (
          "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
          " (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
      )
  }

  items_list = []
  try:
    response = requests.get(url, headers=headers, timeout=8)
    if response.status_code == 200:
      soup = BeautifulSoup(response.content, "xml")
      items = soup.find_all("item")

      for item in items[:5]:
        title = item.title.text.strip() if item.title else ""
        link = item.link.text.strip() if item.link else ""
        pub_date_str = item.pubDate.text.strip() if item.pubDate else ""

        if pub_date_str:
          try:
            pub_dt = parsedate_to_datetime(pub_date_str)
            now_dt = datetime.now(timezone.utc)
            age_minutes = (now_dt - pub_dt).total_seconds() / 60

            if age_minutes > MAX_NEWS_AGE_MINUTES:
              continue
          except Exception:
            pass

        if title and link:
          stock_name = extract_stock_name(title)
          items_list.append({
              "title": title,
              "stock_name": stock_name,
              "link": link,
              "category": get_news_category(title),
              "sentiment": analyze_sentiment(title),
              "source": source_info["name"],
          })
  except Exception as e:
    print(f"Error fetching {source_info['name']}: {e}")

  return items_list


def send_telegram_alert(message):
  """Telegram API Alert Function."""
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


def send_daily_table_report(report_title):
  """9:00 AM आणि 3:30 PM ला Clickable Links सह सुंदर टेब्युलर रिपोर्ट पाठवणे."""
  global daily_stocks_log

  if not daily_stocks_log:
    print(f"ℹ️ No news stored for {report_title} today.")
    return

  msg = f"📊 <b><u>{report_title}</u></b> 📊\n"
  msg += f"📅 <b>Date:</b> {datetime.now().strftime('%d-%b-%Y')}\n"
  msg += f"📈 <b>Tracked Items:</b> {len(daily_stocks_log)}\n"
  msg += "━━━━━━━━━━━━━━━━━━━━━\n\n"

  unique_stocks = {}
  for item in daily_stocks_log:
    s_name = item["stock_name"]
    unique_stocks[s_name] = item

  for idx, (stock, item) in enumerate(unique_stocks.items(), 1):
    s_symbol = "🟢 BULLISH" if "BULLISH" in item["sentiment"] else "🔴 BEARISH"
    msg += f"<b>{idx}. {stock}</b>\n"
    msg += f"   📊 <b>Sentiment:</b> {s_symbol}\n"
    msg += f"   🔗 <a href='{item['link']}'>बातमी वाचण्यासाठी येथे क्लिक करा</a>\n"
    msg += "─────────────────────\n"

  msg += f"\n🤖 <i>Shambhu's Live Market Radar</i>"

  send_telegram_alert(msg)
  print(f"✅ {report_title} Sent Successfully!")

  daily_stocks_log = []


def scan_all_7_sources():
  """सोर्सेस स्कॅन करणे, ९:०० AM / ३:३० PM चे रिपोर्ट्स मॅनेज करणे आणि लाईव्ह मार्केटमध्येच अलर्ट्स पाठवणे."""
  global seen_news_titles, daily_stocks_log, has_sent_9am_report, has_sent_330pm_report

  now = datetime.now()

  # ⏰ १. सकाळी ९:०० वाजता Pre-Market Report पाठवणे
  if now.hour == 9 and now.minute == 0:
    if not has_sent_9am_report:
      send_daily_table_report("MORNING MARKET SENTIMENT REPORT (9:00 AM)")
      has_sent_9am_report = True
  elif now.hour != 9:
    has_sent_9am_report = False

  # ⏰ २. दुपारी ३:३० वाजता Post-Market Report पाठवणे
  if now.hour == 15 and now.minute == 30:
    if not has_sent_330pm_report:
      send_daily_table_report("CLOSING MARKET SENTIMENT REPORT (3:30 PM)")
      has_sent_330pm_report = True
  elif now.hour != 15:
    has_sent_330pm_report = False

  all_latest_news = []
  for source in SOURCES_CONFIG:
    news_items = fetch_news_for_source(source)
    all_latest_news.extend(news_items)

  if not seen_news_titles:
    for news in all_latest_news:
      seen_news_titles.add(get_clean_title(news["title"]))
    print(
        "✅ Initial setup complete. Saved"
        f" {len(seen_news_titles)} fresh news items to memory."
    )
    return

  new_items_to_alert = []
  for news in all_latest_news:
    clean_key = get_clean_title(news["title"])

    if clean_key not in seen_news_titles:
      seen_news_titles.add(clean_key)

      if news["sentiment"] != "⚪ NEUTRAL":
        new_items_to_alert.append(news)
        daily_stocks_log.append({
            "stock_name": news["stock_name"],
            "sentiment": news["sentiment"],
            "link": news["link"],
        })

  # 🚨 ३. फक्त Live Market मध्येच Instant Telegram Alert पाठवणे (09:15 AM - 03:30 PM, Mon-Fri)
  if new_items_to_alert and is_live_market_time():
    msg = f"⚡ <b><u>LIVE MARKET INSTANT ALERT</u></b> ⚡\n"
    msg += f"🔥 <b>Updates: {len(new_items_to_alert)} Item(s)</b>\n"
    msg += f"━━━━━━━━━━━━━━━━━━━━━\n\n"

    for idx, news in enumerate(new_items_to_alert, 1):
      msg += f"<b>{idx}. {news['title']}</b>\n"
      msg += f"📡 <b>Source:</b> {news['source']}\n"
      msg += f"📊 <b>Sentiment:</b> {news['sentiment']}\n"
      msg += f"🏷️ <b>Category:</b> {news['category']}\n"
      msg += f"🔗 <a href='{news['link']}'>बातमी वाचण्यासाठी येथे क्लिक करा</a>\n"
      msg += f"─────────────────────\n\n"

    msg += (
        f"🕒 <b>Time:</b> {datetime.now().strftime('%I:%M:%S %p')}  |  📅"
        f" <b>Date:</b> {datetime.now().strftime('%d-%b-%Y')}\n"
    )
    msg += f"🤖 <i>Shambhu's Live Market Radar</i>"

    send_telegram_alert(msg)
    print(
        "⚡ Live Market Alert Sent"
        f" ({len(new_items_to_alert)} News items)!"
    )
  elif new_items_to_alert:
    print(
        f"ℹ️ {len(new_items_to_alert)} News logged during Off-Market hours."
        " Alerts paused until Live Market."
    )

  if len(seen_news_titles) > 600:
    seen_news_titles = set(list(seen_news_titles)[-300:])


if __name__ == "__main__":
  print(
      "🚀 Starting Live Market News Radar (Reports at 9:00 AM & 3:30 PM with"
      " Clickable Links)..."
  )

  t = threading.Thread(target=run_server)
  t.daemon = True
  t.start()

  scan_all_7_sources()

  print(
      "📡 Active Monitoring: Instant Alerts in Live Market (9:15 AM - 3:30 PM)"
      " Active..."
  )

  while True:
    try:
      scan_all_7_sources()
      time.sleep(CHECK_INTERVAL)
    except Exception as e:
      print(f"Loop Error: {e}")
      time.sleep(10)