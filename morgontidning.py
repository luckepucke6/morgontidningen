"""
morgontidning.py – Master-bot
Kombinerar SVT, NT.se och Tech-nyheter till en daglig HTML-tidning
och laddar upp den till Google Drive för Kobo Libra Colour.
"""

import os, json
from datetime import datetime, timezone, timedelta
from pathlib import Path
import requests
from bs4 import BeautifulSoup
import feedparser

from openai import OpenAI

from html_builder import build_html

# ═══════════════════════════════════════════════════════════════════════════════
#  KONFIGURATION – Ändra här för att anpassa tidningen
# ═══════════════════════════════════════════════════════════════════════════════

# Antal artiklar per sektion
SVT_NYHETER_COUNT = 3     # SVT Nyheter
SVT_SPORT_COUNT   = 2     # SVT Sport
TECH_COUNT        = 6     # Tech & AI

# Poängsättning för Tech (artiklar under TECH_MIN_SCORE filtreras bort)
TECH_MIN_SCORE    = 4     # 1–10

# Artiklar äldre än detta antal timmar ignoreras
MAX_AGE_HOURS     = 48

# Nyckelord som höjer/sänker Tech-artiklar (lägg till egna)
TECH_HIGH_VALUE = [
    "ai", "artificiell intelligens", "llm", "gpt", "sverige",
    "startup", "förvärv", "ipo", "openai", "anthropic", "robotar",
]
TECH_LOW_VALUE = [
    "recension", "guide", "tips", "topp 10", "lista", "quiz",
]

# Väder – koordinater för din stad
# Stockholm: 59.33, 18.07 | Göteborg: 57.70, 11.97 | Malmö: 55.60, 13.00
# Norrköping: 58.59, 16.18 | Linköping: 58.41, 15.62
WEATHER_LAT  = 59.33   # Latitud
WEATHER_LON  = 18.07   # Longitud
WEATHER_CITY = "Stockholm"   # Visas på framsidan

# NT.se – nyckelord för att hitta relevanta artiklar
NT_KEYWORDS = ["dolphins", "ifk norrköping", "peking"]

# ═══════════════════════════════════════════════════════════════════════════════
#  KÄLLOR – Lägg till eller ta bort RSS-flöden här
# ═══════════════════════════════════════════════════════════════════════════════

SVT_FEEDS = {
    "SVT Nyheter": "https://www.svt.se/nyheter/rss.xml",
    "SVT Sport":   "https://www.svt.se/sport/rss.xml",
}

NT_FEEDS = [
    "https://nt.se/rss/",
    "https://nt.se/sport/rss/",
]

TECH_FEEDS = {
    "TechCrunch": "https://techcrunch.com/feed/",
    "The Verge":  "https://www.theverge.com/rss/index.xml",
    "Wired":      "https://www.wired.com/feed/rss",
    "Breakit":    "https://www.breakit.se/feed/artiklar",
    "Di Digital": "https://digital.di.se/rss",
}

# ═══════════════════════════════════════════════════════════════════════════════
#  INTERNT – Ändra inte om du inte vet vad du gör
# ═══════════════════════════════════════════════════════════════════════════════

SEEN_FILE     = Path("nyhetslogg.json")
FEEDBACK_FILE = Path("feedback.txt")

MONTHS_SV = {
    1:"januari", 2:"februari", 3:"mars", 4:"april", 5:"maj", 6:"juni",
    7:"juli", 8:"augusti", 9:"september", 10:"oktober", 11:"november", 12:"december"
}
DAYS_SV = {
    "Monday":"Måndag","Tuesday":"Tisdag","Wednesday":"Onsdag",
    "Thursday":"Torsdag","Friday":"Fredag","Saturday":"Lördag","Sunday":"Söndag"
}

WEATHER_URL = (
    f"https://api.open-meteo.com/v1/forecast"
    f"?latitude={WEATHER_LAT}&longitude={WEATHER_LON}"
    f"&current=temperature_2m,weather_code"
    f"&timezone=Europe%2FStockholm"
)
WEATHER_CODES = {
    0:"Klart", 1:"Mestadels klart", 2:"Delvis molnigt", 3:"Mulet",
    45:"Dimma", 48:"Rimfrost", 51:"Duggregn", 53:"Duggregn", 55:"Duggregn",
    61:"Regn", 63:"Regn", 65:"Kraftigt regn",
    71:"Snö", 73:"Snö", 75:"Kraftigt snöfall",
    80:"Regnskurar", 81:"Regnskurar", 82:"Kraftiga regnskurar",
    95:"Åska", 96:"Åska med hagel", 99:"Åska med hagel",
}


# ── Hjälpfunktioner ───────────────────────────────────────────────────────────
def load_seen() -> set:
    if SEEN_FILE.exists():
        return set(json.loads(SEEN_FILE.read_text()))
    return set()

def save_seen(seen: set):
    SEEN_FILE.write_text(json.dumps(sorted(seen), indent=2, ensure_ascii=False))

def load_feedback() -> tuple[set, set]:
    liked, disliked = set(), set()
    if not FEEDBACK_FILE.exists():
        return liked, disliked
    for line in FEEDBACK_FILE.read_text().splitlines():
        line = line.strip()
        if line.startswith("+"): liked.add(line[1:].strip())
        elif line.startswith("-"): disliked.add(line[1:].strip())
    return liked, disliked

def is_recent(entry) -> bool:
    published = entry.get("published_parsed") or entry.get("updated_parsed")
    if not published:
        return True
    pub_dt = datetime(*published[:6], tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - pub_dt < timedelta(hours=MAX_AGE_HOURS)


# ── Fulltext-scraping (SVT & Tech) ────────────────────────────────────────────
ARTICLE_SELECTORS = [
    "article",
    "[class*='article-body']",
    "[class*='ArticleBody']",
    "[class*='article__body']",
    "[class*='story-body']",
    "[class*='body-text']",
    "[class*='content-body']",
    "main",
]

def scrape_article_text(url: str) -> str:
    """Hämtar fulltexten från en artikel via requests + BeautifulSoup."""
    try:
        resp = requests.get(
            url,
            timeout=15,
            headers={"User-Agent": "Mozilla/5.0 (compatible; nyhetsbot/1.0)"},
        )
        if resp.status_code != 200:
            return ""
        soup = BeautifulSoup(resp.text, "html.parser")

        # Ta bort skräp
        for tag in soup(["script", "style", "nav", "header", "footer",
                         "aside", "figure", "figcaption", "form", "button"]):
            tag.decompose()

        # Prova selektorer i tur och ordning
        container = None
        for sel in ARTICLE_SELECTORS:
            container = soup.select_one(sel)
            if container:
                break

        if not container:
            container = soup.find("body")
        if not container:
            return ""

        paragraphs = [
            p.get_text(separator=" ", strip=True)
            for p in container.find_all("p")
            if len(p.get_text(strip=True)) > 40
        ]
        return "\n\n".join(paragraphs)

    except Exception as e:
        print(f"     ⚠️  Scraping-fel ({url[:60]}…): {e}")
        return ""


# ── Framsidedata ──────────────────────────────────────────────────────────────
def get_weather() -> dict:
    try:
        r = requests.get(WEATHER_URL, timeout=10)
        data = r.json()["current"]
        return {"temp": round(data["temperature_2m"]),
                "desc": WEATHER_CODES.get(data["weather_code"], "Okänt")}
    except Exception as e:
        print(f"   ⚠️  Väder-fel: {e}")
        return {"temp": "?", "desc": "Okänt"}

def get_exchange_rate() -> str:
    try:
        r = requests.get("https://api.frankfurter.app/latest?from=USD&to=SEK", timeout=10)
        return f"{r.json()['rates']['SEK']:.2f}"
    except Exception as e:
        print(f"   ⚠️  Valuta-fel: {e}")
        return "?"

def get_nameday() -> str:
    try:
        now = datetime.now()
        r   = requests.get(f"https://api.dryg.net/dagar/v2.1/{now.year}/{now.month}/{now.day}", timeout=10)
        names = r.json().get("dagar", [{}])[0].get("namnsdag", [])
        return ", ".join(names) if names else "–"
    except Exception as e:
        print(f"   ⚠️  Namnsdag-fel: {e}")
        return "?"


# ── SVT-scraper ───────────────────────────────────────────────────────────────
SVT_HIGH = ["riksdag","regering","vm","em","os","final","landslaget","allsvenskan","breaking","just nu"]

def score_svt(entry, source: str) -> int:
    text = (entry.get("title","") + " " + entry.get("summary","")).lower()
    score = 5
    for kw in SVT_HIGH:
        if kw in text: score += 1; break
    if source == "SVT Sport" and any(kw in text for kw in ["vm","em","os","final","landslaget"]):
        score += 1
    return max(1, min(10, score))

def fetch_svt_articles(seen: set) -> tuple[list, list]:
    nyheter, sport = [], []
    for source, url in SVT_FEEDS.items():
        print(f"   Läser {source}…")
        feed = feedparser.parse(url)
        for entry in feed.entries:
            link = entry.get("link","")
            if not link or link in seen or not is_recent(entry):
                continue
            art = {
                "url":     link,
                "title":   entry.get("title",""),
                "summary": entry.get("summary",""),
                "text":    "",   # hämtas nedan
                "source":  source,
                "score":   score_svt(entry, source),
                "date":    entry.get("published",""),
            }
            (nyheter if source == "SVT Nyheter" else sport).append(art)
    nyheter.sort(key=lambda x: x["score"], reverse=True)
    sport.sort(key=lambda x: x["score"], reverse=True)
    top = nyheter[:SVT_NYHETER_COUNT] + sport[:SVT_SPORT_COUNT]

    print(f"   Hämtar fulltext för {len(top)} SVT-artiklar…")
    for art in top:
        art["text"] = scrape_article_text(art["url"])

    return nyheter[:SVT_NYHETER_COUNT], sport[:SVT_SPORT_COUNT]


# ── Tech-scraper ──────────────────────────────────────────────────────────────
def score_tech(entry, liked: set, disliked: set) -> int:
    url  = entry.get("link","")
    text = (entry.get("title","") + " " + entry.get("summary","")).lower()
    score = 5
    if url in liked:    score += 2
    if url in disliked: score -= 3
    for kw in TECH_HIGH_VALUE:
        if kw in text: score += 1; break
    for kw in TECH_LOW_VALUE:
        if kw in text: score -= 1; break
    return max(1, min(10, score))

def fetch_tech_articles(seen: set, liked: set, disliked: set) -> list:
    candidates = []
    for source, url in TECH_FEEDS.items():
        print(f"   Läser {source}…")
        feed = feedparser.parse(url)
        for entry in feed.entries:
            link = entry.get("link","")
            if not link or link in seen or not is_recent(entry):
                continue
            score = score_tech(entry, liked, disliked)
            if score >= TECH_MIN_SCORE:
                candidates.append({
                    "url":     link,
                    "title":   entry.get("title",""),
                    "summary": entry.get("summary",""),
                    "text":    "",   # hämtas nedan
                    "source":  source,
                    "score":   score,
                    "date":    entry.get("published",""),
                })
    candidates.sort(key=lambda x: x["score"], reverse=True)
    top = candidates[:TECH_COUNT]

    print(f"   Hämtar fulltext för {len(top)} Tech-artiklar…")
    for art in top:
        art["text"] = scrape_article_text(art["url"])

    return top


# ── NT.se RSS-scraper ────────────────────────────────────────────────────────
def nt_fetch_articles(seen: set) -> list:
    """Hämtar nyheter om Dolphins och IFK Norrköping via NT.se RSS (utan inloggning)."""
    articles = []
    for feed_url in NT_FEEDS:
        feed = feedparser.parse(feed_url)
        for entry in feed.entries:
            url   = entry.get("link", "")
            title = entry.get("title", "")
            if not url or url in seen or not is_recent(entry):
                continue
            text_lower = (title + " " + entry.get("summary", "")).lower()
            if not any(kw in text_lower for kw in NT_KEYWORDS):
                continue
            print(f"   → {title}")
            articles.append({
                "url":     url,
                "title":   title,
                "summary": entry.get("summary", ""),
                "text":    "",   # NT kräver inloggning för fulltext
                "source":  "NT.se",
                "score":   10,
                "date":    entry.get("published", ""),
            })
    return articles


# ── AI-sammanfattning ─────────────────────────────────────────────────────────
def generate_ai_summary(svt_nyheter, svt_sport, nt_articles, tech_articles) -> str:
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    headlines = (
        [f"[Nyheter] {a['title']}" for a in svt_nyheter] +
        [f"[Sport SVT] {a['title']}" for a in svt_sport] +
        [f"[NT Sport] {a['title']}" for a in nt_articles] +
        [f"[Tech] {a['title']}" for a in tech_articles]
    )
    now   = datetime.now()
    today = f"{now.day} {MONTHS_SV[now.month]} {now.year}"
    resp  = client.chat.completions.create(
        model="gpt-4o-mini",
        max_tokens=500,
        messages=[{"role":"user","content":(
            f"Du är redaktör för en personlig morgontidning. Datum: {today}.\n"
            "Skriv en 'Dagens översikt' på svenska (max 120 ord). "
            "Var konkret och informativ. Löpande text, inga punktlistor.\n\n"
            "Rubriker:\n" + "\n".join(headlines)
        )}]
    )
    return resp.choices[0].message.content


# ── Google Drive OAuth-uppladdning ────────────────────────────────────────────
def upload_to_drive(filepath: str, folder_id: str,
                    client_id: str, client_secret: str, refresh_token: str) -> str:
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    creds = Credentials(
        token=None, refresh_token=refresh_token,
        client_id=client_id, client_secret=client_secret,
        token_uri="https://oauth2.googleapis.com/token",
        scopes=["https://www.googleapis.com/auth/drive.file"],
    )
    creds.refresh(Request())
    service  = build("drive", "v3", credentials=creds)
    filename = os.path.basename(filepath)

    # Ta bort gammal version om den finns
    existing = service.files().list(
        q=f"name='{filename}' and '{folder_id}' in parents and trashed=false",
        fields="files(id)"
    ).execute().get("files", [])
    for f in existing:
        service.files().delete(fileId=f["id"]).execute()

    media  = MediaFileUpload(filepath, mimetype="text/html", resumable=True)
    result = service.files().create(
        body={"name": filename, "parents": [folder_id]},
        media_body=media, fields="id"
    ).execute()
    return result.get("id", "?")


# ── Huvudlogik ────────────────────────────────────────────────────────────────
def main():
    now      = datetime.now()
    date_iso = now.strftime("%Y-%m-%d")
    date_sv  = f"{now.day} {MONTHS_SV[now.month]} {now.year}"
    day_sv   = DAYS_SV.get(now.strftime("%A"), now.strftime("%A"))

    print(f"📰 Morgontidningen {date_sv} – startar…\n")

    seen            = load_seen()
    liked, disliked = load_feedback()

    print("📊 Hämtar framsidedata…")
    weather  = get_weather()
    usd_sek  = get_exchange_rate()
    nameday  = get_nameday()
    week_num = now.isocalendar()[1]
    cover_data = {
        "date": date_sv, "weekday": day_sv, "week": week_num,
        "nameday": nameday, "weather": weather, "usd_sek": usd_sek, "weather_city": WEATHER_CITY,
    }
    print(f"   {day_sv} v.{week_num} · {weather['temp']}°C {weather['desc']} · "
          f"USD/SEK {usd_sek} · Namnsdag: {nameday}")

    print("\n📡 SVT Nyheter & Sport…")
    svt_nyheter, svt_sport = fetch_svt_articles(seen)
    print(f"   {len(svt_nyheter)} nyheter, {len(svt_sport)} sport")

    print("\n📡 Tech & AI…")
    tech_articles = fetch_tech_articles(seen, liked, disliked)
    print(f"   {len(tech_articles)} artiklar")

    print("\n📡 NT.se (Playwright)…")
    nt_articles = nt_fetch_articles(seen)
    print(f"   {len(nt_articles)} artiklar om Dolphins/IFK")

    all_articles = svt_nyheter + svt_sport + nt_articles + tech_articles
    if not all_articles:
        print("\n⚠️  Inga nya artiklar idag – avslutar.")
        return

    print("\n🤖 Genererar AI-sammanfattning…")
    try:
        ai_summary = generate_ai_summary(svt_nyheter, svt_sport, nt_articles, tech_articles)
        print(f"   ✅ Klar ({len(ai_summary)} tecken)")
    except Exception as e:
        print(f"   ⚠️  AI-fel: {e}")
        ai_summary = "Kunde inte generera sammanfattning idag."

    print("\n📄 Bygger HTML-tidning…")
    html_filename = f"Morgontidningen_{date_iso}.html"
    build_html(
        filename=html_filename,
        cover_data=cover_data,
        ai_summary=ai_summary,
        svt_nyheter=svt_nyheter,
        svt_sport=svt_sport,
        nt_articles=nt_articles,
        tech_articles=tech_articles,
    )
    size_kb = Path(html_filename).stat().st_size // 1024
    print(f"   ✅ {html_filename} ({size_kb} KB)")

    print("\n☁️  Laddar upp till Google Drive…")
    file_id = upload_to_drive(
        filepath=html_filename,
        folder_id=os.environ["GOOGLE_DRIVE_FOLDER_ID"],
        client_id=os.environ["GOOGLE_CLIENT_ID"],
        client_secret=os.environ["GOOGLE_CLIENT_SECRET"],
        refresh_token=os.environ["GOOGLE_REFRESH_TOKEN"],
    )
    print(f"   ✅ Uppladdad! Drive ID: {file_id}")

    for art in all_articles:
        seen.add(art["url"])
    save_seen(seen)

    print(f"\n🏁 Klart! Morgontidningen {date_sv} är på väg till din Kobo. God läsning!")


if __name__ == "__main__":
    main()
