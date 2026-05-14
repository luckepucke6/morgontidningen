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

# Väder
WEATHER_LAT  = 59.33
WEATHER_LON  = 18.07
WEATHER_CITY = "Stockholm"

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
#  FUNKTIONER (Scraping & Logik)
# ═══════════════════════════════════════════════════════════════════════════════

# [Behåll load_seen, save_seen, is_recent och scrape_article_text från din originalfil]
# Jag utelämnar dem här för att spara plats, men de ska vara kvar exakt som de är.

def fetch_generic_articles(feed_dict, count, seen, section_name) -> list:
    """Hjälpfunktion för att hämta artiklar från olika kategorier."""
    articles = []
    for source, url in feed_dict.items():
        print(f"   Läser {source}…")
        feed = feedparser.parse(url)
        for entry in feed.entries:
            link = entry.get("link", "")
            if not link or link in seen or not is_recent(entry):
                continue
            articles.append({
                "url":     link,
                "title":   entry.get("title", ""),
                "summary": BeautifulSoup(entry.get("summary", ""), "html.parser").get_text(separator=" "),
                "text":    "", 
                "source":  source,
                "date":    entry.get("published", ""),
            })
    
    articles = articles[:count]
    print(f"   Hämtar fulltext för {len(articles)} {section_name}-artiklar…")
    for art in articles:
        art["text"] = scrape_article_text(art["url"])
    return articles

# ── Huvudlogik ────────────────────────────────────────────────────────────────
def main():
    now      = datetime.now()
    date_iso = now.strftime("%Y-%m-%d")
    date_sv  = f"{now.day} {MONTHS_SV[now.month]} {now.year}"
    day_sv   = DAYS_SV.get(now.strftime("%A"), now.strftime("%A"))

    print(f"📰 Morgontidningen {date_sv} – startar…\n")
    seen = load_seen()

    print("📊 Hämtar framsidedata…")
    cover_data = {
        "date": date_sv, "weekday": day_sv, "week": now.isocalendar()[1],
        "nameday": get_nameday(), "weather": get_weather(), 
        "usd_sek": get_exchange_rate(), "weather_city": WEATHER_CITY,
    }

    print("\n📡 Nyheter & Sport…")
    svt_nyheter, svt_sport = fetch_svt_articles(seen)

    print("\n📡 Ekonomi…")
    econ_articles = fetch_generic_articles(ECONOMY_FEEDS, ECONOMY_COUNT, seen, "Ekonomi")

    print("\n📡 Utrikes…")
    world_articles = fetch_generic_articles(WORLD_FEEDS, WORLD_COUNT, seen, "Utrikes")

    print("\n📡 Vetenskap…")
    science_articles = fetch_generic_articles(SCIENCE_FEEDS, SCIENCE_COUNT, seen, "Vetenskap")

    print("\n📡 Tech…")
    tech_articles = fetch_tech_articles(seen, set(), set()) # Liknande din gamla funktion

    all_articles = svt_nyheter + svt_sport + econ_articles + world_articles + science_articles + tech_articles

    print("\n🤖 Genererar AI-sammanfattning…")
    ai_summary = generate_ai_summary(svt_nyheter, svt_sport, world_articles, econ_articles)

    print("\n📄 Bygger HTML-tidning…")
    html_filename = f"Morgontidningen_{date_iso}.html"
    build_html(
        filename=html_filename,
        cover_data=cover_data,
        ai_summary=ai_summary,
        svt_nyheter=svt_nyheter,
        svt_sport=svt_sport,
        econ_articles=econ_articles,
        world_articles=world_articles,
        science_articles=science_articles,
        tech_articles=tech_articles,
    )

    # [Uppladdning och spara 'seen' som tidigare...]
