"""
morgontidning.py – Master-bot
Kombinerar SVT, NT.se och Tech-nyheter till en daglig EPUB
och laddar upp den till Google Drive (OAuth) för Kobo Libra Colour.
"""

import os, json, asyncio
from datetime import datetime, timezone, timedelta
from pathlib import Path
import requests
import feedparser
from playwright.async_api import async_playwright
from openai import OpenAI

from epub_builder import build_epub

# ── Svenska datum ────────────────────────────────────────────────────────────
MONTHS_SV = {
    1:"januari", 2:"februari", 3:"mars", 4:"april", 5:"maj", 6:"juni",
    7:"juli", 8:"augusti", 9:"september", 10:"oktober", 11:"november", 12:"december"
}
DAYS_SV = {
    "Monday":"Måndag","Tuesday":"Tisdag","Wednesday":"Onsdag",
    "Thursday":"Torsdag","Friday":"Fredag","Saturday":"Lördag","Sunday":"Söndag"
}

# ── Konfiguration ────────────────────────────────────────────────────────────
SEEN_FILE     = Path("nyhetslogg.json")
FEEDBACK_FILE = Path("feedback.txt")
MAX_AGE_HOURS = 48

SVT_FEEDS = {
    "SVT Nyheter": "https://www.svt.se/nyheter/rss.xml",
    "SVT Sport":   "https://www.svt.se/sport/rss.xml",
}
SVT_NYHETER_COUNT = 3
SVT_SPORT_COUNT   = 2

NT_FEEDS    = ["https://nt.se/rss/", "https://nt.se/sport/rss/"]
NT_KEYWORDS = ["dolphins", "ifk norrköping", "peking"]

TECH_FEEDS = {
    "TechCrunch": "https://techcrunch.com/feed/",
    "The Verge":  "https://www.theverge.com/rss/index.xml",
    "Wired":      "https://www.wired.com/feed/rss",
    "Breakit":    "https://www.breakit.se/feed/artiklar",
    "Di Digital": "https://digital.di.se/rss",
}
TECH_COUNT      = 6
TECH_MIN_SCORE  = 4
TECH_HIGH_VALUE = ["ai","artificiell intelligens","llm","gpt","sverige","startup","förvärv","ipo","openai","anthropic"]
TECH_LOW_VALUE  = ["recension","guide","tips","topp 10","lista","quiz"]

WEATHER_URL = (
    "https://api.open-meteo.com/v1/forecast"
    "?latitude=58.59&longitude=16.18"
    "&current=temperature_2m,weather_code"
    "&timezone=Europe%2FStockholm"
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
                "text":    "",
                "source":  source,
                "score":   score_svt(entry, source),
                "date":    entry.get("published",""),
            }
            (nyheter if source == "SVT Nyheter" else sport).append(art)
    nyheter.sort(key=lambda x: x["score"], reverse=True)
    sport.sort(key=lambda x: x["score"], reverse=True)
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
                    "text":    "",
                    "source":  source,
                    "score":   score,
                    "date":    entry.get("published",""),
                })
    candidates.sort(key=lambda x: x["score"], reverse=True)
    return candidates[:TECH_COUNT]


# ── NT.se Playwright-scraper ──────────────────────────────────────────────────
async def nt_fetch_articles(seen: set, username: str, password: str) -> list:
    articles = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()

        # ── Steg 1: Ladda startsidan ──────────────────────────────────────────
        print("   Laddar NT.se startsida…")
        await page.goto("https://nt.se", wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)

        # ── Steg 2: Hantera SP Consent Message cookie-banner (iframe) ─────────
        # NT.se använder "SP Consent Message" som ligger i en iframe
        print("   Letar efter cookie-banner…")
        cookie_clicked = False
        for frame in page.frames:
            try:
                # Prova att hitta synlig acceptera-knapp i varje frame
                btn = await frame.query_selector(
                    "button[title*='Godkänn'], button[title*='Accept'], "
                    "button:has-text('Godkänn alla'), button:has-text('Acceptera alla'), "
                    "button:has-text('Accept all'), [data-testid='accept-all']"
                )
                if btn and await btn.is_visible():
                    await btn.click()
                    await page.wait_for_timeout(1500)
                    cookie_clicked = True
                    print("   ✅ Cookie-banner (iframe) stängd")
                    break
            except:
                pass
        if not cookie_clicked:
            print("   ℹ️  Ingen cookie-banner hittad, fortsätter")

        # ── Steg 3: Hitta synlig Logga in-länk på startsidan ──────────────────
        print("   Letar efter Logga in-knapp…")
        try:
            # :visible säkerställer att vi inte klickar på dolda spök-knappar
            await page.click(
                "a:visible:has-text('Logga in'), button:visible:has-text('Logga in')",
                timeout=8000
            )
            await page.wait_for_load_state("networkidle", timeout=20000)
            await page.wait_for_timeout(2000)
            print(f"   ✅ På inloggningssidan: {page.url}")
        except:
            print("   ℹ️  Hittade ingen synlig Logga in-knapp, navigerar direkt")
            await page.goto("https://nt.se/mitt-konto/logga-in/",
                            wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(2000)

        # ── Steg 4: Fyll i e-post (steg 1 av 2-stegsinloggning) ──────────────
        email_selector = (
            "input[type='email']:visible, input[name='Username']:visible, "
            "input[id='Username']:visible, input[name='email']:visible"
        )
        await page.wait_for_selector(email_selector, timeout=15000)
        await page.fill(email_selector, username)
        print(f"   ✅ E-post ifylld")

        # Klicka synlig Nästa-knapp
        try:
            await page.click(
                "button:visible:has-text('Nästa'), button:visible:has-text('Fortsätt'), "
                "input[type='submit']:visible",
                timeout=5000
            )
            await page.wait_for_timeout(2000)
        except:
            pass

        # ── Steg 5: Fyll i lösenord ───────────────────────────────────────────
        await page.wait_for_selector("input[type='password']:visible", timeout=10000)
        await page.fill("input[type='password']", password)

        # Klicka synlig inloggningsknapp
        await page.click(
            "button:visible[type='submit'], input:visible[type='submit']",
            timeout=5000
        )
        await page.wait_for_load_state("networkidle", timeout=20000)
        await page.wait_for_timeout(2000)
        print(f"   ✅ Inloggad på NT.se (nu på {page.url})")

        for feed_url in NT_FEEDS:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries:
                url   = entry.get("link","")
                title = entry.get("title","")
                if not url or url in seen or not is_recent(entry):
                    continue
                if not any(kw in (title + " " + entry.get("summary","")).lower() for kw in NT_KEYWORDS):
                    continue

                print(f"   → {title}")
                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=20000)
                    await page.wait_for_timeout(1500)
                    content = await page.evaluate("""() => {
                        const sel = ['article','[class*="ArticleBody"]','[class*="article-body"]',
                                     '[class*="article__body"]','[class*="story-body"]'];
                        let el = null;
                        for (const s of sel) { el = document.querySelector(s); if (el) break; }
                        if (!el) return '';
                        return Array.from(el.querySelectorAll('p'))
                            .map(p => p.innerText.trim())
                            .filter(t => t.length > 30)
                            .join('\\n\\n');
                    }""")
                    articles.append({
                        "url": url, "title": title,
                        "summary": entry.get("summary",""),
                        "text": content or "", "source": "NT.se",
                        "score": 10, "date": entry.get("published",""),
                    })
                except Exception as e:
                    print(f"     ⚠️  Scraping-fel: {e}")
                    articles.append({
                        "url": url, "title": title,
                        "summary": entry.get("summary",""),
                        "text": "", "source": "NT.se",
                        "score": 10, "date": entry.get("published",""),
                    })
        await browser.close()
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
        token=None,
        refresh_token=refresh_token,
        client_id=client_id,
        client_secret=client_secret,
        token_uri="https://oauth2.googleapis.com/token",
        scopes=["https://www.googleapis.com/auth/drive.file"],
    )
    creds.refresh(Request())

    service  = build("drive", "v3", credentials=creds)
    filename = os.path.basename(filepath)

    # Ta bort gammal fil med samma namn om den finns
    existing = service.files().list(
        q=f"name='{filename}' and '{folder_id}' in parents and trashed=false",
        fields="files(id)"
    ).execute().get("files", [])
    for f in existing:
        service.files().delete(fileId=f["id"]).execute()

    media  = MediaFileUpload(filepath, mimetype="application/epub+zip", resumable=True)
    result = service.files().create(
        body={"name": filename, "parents": [folder_id]},
        media_body=media,
        fields="id"
    ).execute()
    return result.get("id", "?")


# ── Huvudlogik ────────────────────────────────────────────────────────────────
async def main():
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
        "nameday": nameday, "weather": weather, "usd_sek": usd_sek,
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
    nt_articles = await nt_fetch_articles(
        seen, os.environ["NT_USERNAME"], os.environ["NT_PASSWORD"]
    )
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

    print("\n📚 Bygger EPUB…")
    epub_filename = f"Morgontidningen_{date_iso}.epub"
    build_epub(
        filename=epub_filename,
        cover_data=cover_data,
        ai_summary=ai_summary,
        svt_nyheter=svt_nyheter,
        svt_sport=svt_sport,
        nt_articles=nt_articles,
        tech_articles=tech_articles,
    )
    size_kb = Path(epub_filename).stat().st_size // 1024
    print(f"   ✅ {epub_filename} ({size_kb} KB)")

    print("\n☁️  Laddar upp till Google Drive…")
    file_id = upload_to_drive(
        filepath=epub_filename,
        folder_id=os.environ["GOOGLE_DRIVE_FOLDER_ID"],
        client_id=os.environ["GOOGLE_CLIENT_ID"],
        client_secret=os.environ["GOOGLE_CLIENT_SECRET"],
        refresh_token=os.environ["GOOGLE_REFRESH_TOKEN"],
    )
    print(f"   ✅ Uppladdad! Drive ID: {file_id}")

    for art in all_articles:
        seen.add(art["url"])
    save_seen(seen)

    print(f"\n🏁 Klart! Morgontidningen {date_sv} ligger i din Google Drive. God läsning!")


if __name__ == "__main__":
    asyncio.run(main())
