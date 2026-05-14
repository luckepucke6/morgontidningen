import os, json
from datetime import datetime, timezone, timedelta
from pathlib import Path
import requests
from bs4 import BeautifulSoup
import feedparser
from openai import OpenAI
from html_builder import build_html

# ═══════════════════════════════════════════════════════════════════════════════
#  KONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════

SVT_NYHETER_COUNT = 3
SVT_SPORT_COUNT   = 2
ECONOMY_COUNT     = 4
SCIENCE_COUNT     = 3
WORLD_COUNT       = 4
TECH_COUNT        = 5

MAX_AGE_HOURS     = 48

WEATHER_LAT  = 58.59   # Norrköping (ändra om du vill)
WEATHER_LON  = 16.18
WEATHER_CITY = "Norrköping"

# ═══════════════════════════════════════════════════════════════════════════════
#  KÄLLOR
# ═══════════════════════════════════════════════════════════════════════════════

SVT_FEEDS = {
    "SVT Nyheter": "https://www.svt.se/nyheter/rss.xml",
    "SVT Sport":   "https://www.svt.se/sport/rss.xml",
}

ECONOMY_FEEDS = {
    "Omni Ekonomi": "https://omni.se/ekonomi/rss",
    "Di Digital":   "https://digital.di.se/rss",
}

SCIENCE_FEEDS = {
    "Forskning & Framsteg": "https://fof.se/rss.xml",
    "NASA": "https://www.nasa.gov/rss/dyn/breaking_news.rss",
}

WORLD_FEEDS = {
    "BBC World": "http://feeds.bbci.co.uk/news/world/rss.xml",
    "The Guardian": "https://www.theguardian.com/world/rss",
}

TECH_FEEDS = {
    "TechCrunch": "https://techcrunch.com/feed/",
    "The Verge":  "https://www.theverge.com/rss/index.xml",
    "Wired":      "https://www.wired.com/feed/rss",
    "Breakit":    "https://www.breakit.se/feed/artiklar",
}

# ═══════════════════════════════════════════════════════════════════════════════
#  INTERNT & HJÄLPFUNKTIONER
# ═══════════════════════════════════════════════════════════════════════════════

SEEN_FILE = Path("nyhetslogg.json")
MONTHS_SV = {1:"januari", 2:"februari", 3:"mars", 4:"april", 5:"maj", 6:"juni", 7:"juli", 8:"augusti", 9:"september", 10:"oktober", 11:"november", 12:"december"}
DAYS_SV = {"Monday":"Måndag","Tuesday":"Tisdag","Wednesday":"Onsdag","Thursday":"Torsdag","Friday":"Fredag","Saturday":"Lördag","Sunday":"Söndag"}

def load_seen():
    if SEEN_FILE.exists():
        try: return set(json.loads(SEEN_FILE.read_text()))
        except: return set()
    return set()

def save_seen(seen):
    SEEN_FILE.write_text(json.dumps(sorted(list(seen)), indent=2, ensure_ascii=False))

def is_recent(entry):
    pub = entry.get("published_parsed") or entry.get("updated_parsed")
    if not pub: return True
    dt = datetime(*pub[:6], tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - dt < timedelta(hours=MAX_AGE_HOURS)

def scrape_article_text(url):
    try:
        resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        if resp.status_code != 200: return ""
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "header", "footer", "aside"]): tag.decompose()
        paragraphs = [p.get_text(strip=True) for p in soup.find_all("p") if len(p.get_text(strip=True)) > 50]
        return "\n\n".join(paragraphs[:10])
    except: return ""

def get_weather():
    try:
        url = f"https://api.open-meteo.com/v1/forecast?latitude={WEATHER_LAT}&longitude={WEATHER_LON}&current=temperature_2m,weather_code&timezone=Europe%2FStockholm"
        data = requests.get(url).json()["current"]
        return {"temp": round(data["temperature_2m"]), "desc": "Växlande"}
    except: return {"temp": "?", "desc": "Okänt"}

def get_exchange_rate():
    try: return f"{requests.get('https://api.frankfurter.app/latest?from=USD&to=SEK').json()['rates']['SEK']:.2f}"
    except: return "?"

def get_nameday():
    try:
        d = datetime.now()
        r = requests.get(f"https://api.dryg.net/dagar/v2.1/{d.year}/{d.month}/{d.day}").json()
        return ", ".join(r["dagar"][0]["namnsdag"])
    except: return "-"

# ═══════════════════════════════════════════════════════════════════════════════
#  HÄMTNINGS-LOGIK
# ═══════════════════════════════════════════════════════════════════════════════

def fetch_section(feed_dict, count, seen, name):
    articles = []
    for source, url in feed_dict.items():
        print(f"   Läser {source}...")
        feed = feedparser.parse(url)
        for entry in feed.entries:
            link = entry.get("link", "")
            if not link or link in seen or not is_recent(entry): continue
            
            summary = BeautifulSoup(entry.get("summary", ""), "html.parser").get_text(separator=" ")
            articles.append({
                "url": link, "title": entry.get("title", ""), "summary": summary,
                "text": "", "source": source, "date": entry.get("published", "")
            })
    articles = articles[:count]
    for art in articles: art["text"] = scrape_article_text(art["url"])
    return articles

def generate_ai_summary(all_articles):
    try:
        client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
        headlines = [f"- {a['title']}" for a in all_articles[:15]]
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role":"user","content": f"Skriv en kort morgonöversikt (max 100 ord) baserat på dessa rubriker:\n" + "\n".join(headlines)}]
        )
        return resp.choices[0].message.content
    except: return "Kunde inte generera sammanfattning."

def upload_to_drive(filepath):
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    creds = Credentials(None, refresh_token=os.environ["GOOGLE_REFRESH_TOKEN"], 
                        client_id=os.environ["GOOGLE_CLIENT_ID"], client_secret=os.environ["GOOGLE_CLIENT_SECRET"], 
                        token_uri="https://oauth2.googleapis.com/token")
    service = build("drive", "v3", credentials=creds)
    media = MediaFileUpload(filepath, mimetype="text/html")
    service.files().create(body={"name": os.path.basename(filepath), "parents": [os.environ["GOOGLE_DRIVE_FOLDER_ID"]]}, media_body=media).execute()

# ── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    now = datetime.now()
    print(f"📰 Startar Morgontidningen {now.strftime('%Y-%m-%d')}")
    seen = load_seen()

    cover_data = {
        "date": f"{now.day} {MONTHS_SV[now.month]} {now.year}",
        "weekday": DAYS_SV.get(now.strftime("%A"), ""),
        "week": now.isocalendar()[1],
        "nameday": get_nameday(), "weather": get_weather(), 
        "usd_sek": get_exchange_rate(), "weather_city": WEATHER_CITY
    }

    svt_nyheter = fetch_section(SVT_FEEDS, SVT_NYHETER_COUNT, seen, "SVT")
    econ_articles = fetch_section(ECONOMY_FEEDS, ECONOMY_COUNT, seen, "Ekonomi")
    world_articles = fetch_section(WORLD_FEEDS, WORLD_COUNT, seen, "Utrikes")
    science_articles = fetch_section(SCIENCE_FEEDS, SCIENCE_COUNT, seen, "Vetenskap")
    tech_articles = fetch_section(TECH_FEEDS, TECH_COUNT, seen, "Tech")

    all_arts = svt_nyheter + econ_articles + world_articles + science_articles + tech_articles
    ai_summary = generate_ai_summary(all_arts)

    filename = f"Morgontidningen_{now.strftime('%Y-%m-%d')}.html"
    build_html(filename, cover_data, ai_summary, svt_nyheter, [], econ_articles, world_articles, science_articles, tech_articles)
    
    upload_to_drive(filename)
    for a in all_arts: seen.add(a["url"])
    save_seen(seen)
    print("🏁 Klart!")

if __name__ == "__main__":
    main()
