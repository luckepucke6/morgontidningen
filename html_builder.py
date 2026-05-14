"""
html_builder.py – Bygger en enda HTML-fil med alla artiklar.
Enkel, robust, inga externa beroenden. Kobo läser den direkt.
"""

import re
import html


CSS = """
body {
    font-family: Georgia, serif;
    font-size: 16px;
    line-height: 1.7;
    max-width: 780px;
    margin: 0 auto;
    padding: 20px 24px;
    color: #111;
    background: #fff;
}
h1 { font-size: 2em; margin: 0.3em 0; }
h2 { font-size: 1.5em; margin: 1.2em 0 0.3em; border-bottom: 1px solid #ccc; padding-bottom: 0.2em; }
h3 { font-size: 1.1em; margin: 0.8em 0 0.2em; }
p  { margin: 0.5em 0; }
a  { color: #333; text-decoration: none; }
hr { border: none; border-top: 2px solid #333; margin: 2em 0; }

.cover {
    text-align: center;
    padding: 2em 0 1em;
    border-bottom: 3px double #222;
    margin-bottom: 2em;
}
.cover h1 {
    font-size: 2.6em;
    letter-spacing: 0.05em;
    margin-bottom: 0.2em;
}
.cover-date { font-size: 0.95em; color: #555; margin-bottom: 1.5em; }

.meta-table { width: 100%; border-collapse: collapse; margin: 1em auto; max-width: 400px; }
.meta-table td { padding: 0.4em 0.6em; border-bottom: 1px solid #ddd; font-size: 0.9em; }
.meta-label { font-weight: bold; }
.meta-value { text-align: right; }

.ai-box {
    border-left: 4px solid #555;
    padding: 0.7em 1em;
    margin: 1.5em 0;
    font-style: italic;
    background: #f8f8f8;
}
.ai-title { font-style: normal; font-weight: bold; font-size: 0.85em;
            text-transform: uppercase; letter-spacing: 0.05em; color: #555;
            margin-bottom: 0.4em; }

.toc { margin: 2em 0; padding: 1em; border: 1px solid #ddd; }
.toc h2 { border: none; margin-top: 0; }
.toc ul { margin: 0; padding-left: 1.2em; }
.toc li { margin: 0.3em 0; }
.toc .section-header { font-weight: bold; list-style: none; margin-left: -1.2em; margin-top: 0.8em; }

.section-divider {
    text-align: center;
    padding: 1.5em 0;
    margin: 2em 0;
    border-top: 2px solid #222;
    border-bottom: 2px solid #222;
    page-break-before: always;
}
.section-divider h2 {
    font-size: 1.8em;
    border: none;
    margin: 0;
}

.article { margin-bottom: 3em; padding-bottom: 1.5em; border-bottom: 1px solid #eee; }
.article-meta { font-size: 0.8em; color: #666; margin-bottom: 0.7em; }
.article-ingress { font-style: italic; color: #333; margin-bottom: 0.8em; }
.back-link { font-size: 0.8em; color: #888; margin-top: 1em; }
.no-text { color: #888; font-style: italic; }
"""


def e(text) -> str:
    """HTML-escape a string."""
    return html.escape(str(text or ""), quote=False)


def slugify(text: str, index: int) -> str:
    text = re.sub(r"[^a-z0-9]", "-", text.lower())
    return f"art-{index}-{text[:30]}"


def build_html(
    filename: str,
    cover_data: dict,
    ai_summary: str,
    svt_nyheter: list,
    svt_sport: list,
    nt_articles: list,
    tech_articles: list,
):
    sections = [
        ("SVT Nyheter", "📺", svt_nyheter),
        ("SVT Sport",   "⚽", svt_sport),
        ("NT Sport",    "🏈", nt_articles),
        ("Tech & AI",   "💻", tech_articles),
    ]

    w             = cover_data.get("weather", {})
    date_str      = e(cover_data.get("date", ""))
    weekday       = e(cover_data.get("weekday", ""))
    week          = e(cover_data.get("week", ""))
    nameday       = e(cover_data.get("nameday", "–"))
    temp          = e(w.get("temp", "?"))
    desc          = e(w.get("desc", ""))
    weather_city  = e(cover_data.get("weather_city", ""))
    usd_sek       = e(cover_data.get("usd_sek", "?"))
    summary       = e(ai_summary or "")
    total         = sum(len(arts) for _, _, arts in sections)

    parts = []

    # ── DOCTYPE + HEAD ───────────────────────────────────────────────────────
    parts.append(f"""<!DOCTYPE html>
<html lang="sv">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Morgontidningen {date_str}</title>
<style>{CSS}</style>
</head>
<body>
""")

    # ── FRAMSIDA ─────────────────────────────────────────────────────────
    parts.append(f"""<div class="cover">
  <h1>Morgontidningen</h1>
  <p class="cover-date">{weekday} {date_str} &nbsp;·&nbsp; Vecka {week}</p>
  <div class="ai-box">
    <p class="ai-title">Dagens översikt</p>
    <p>{summary}</p>
  </div>
  <table class="meta-table">
    <tr><td class="meta-label">🎂 Namnsdag</td><td class="meta-value">{nameday}</td></tr>
    <tr><td class="meta-label">🌤 Väder {weather_city}</td><td class="meta-value">{temp}°C · {desc}</td></tr>
    <tr><td class="meta-label">💵 USD/SEK</td><td class="meta-value">{usd_sek} kr</td></tr>
    <tr><td class="meta-label">📰 Artiklar idag</td><td class="meta-value">{total} st</td></tr>
  </table>
</div>
""")

    # ── INNEHÅLLSFÖRTECKNING ──────────────────────────────────────────────────
    parts.append('<div class="toc"><h2>Innehåll</h2><ul>\n')
    art_index = 0
    toc_items = []  # (slug, title, section)
    for sec_title, _, articles in sections:
        if not articles:
            continue
        parts.append(f'<li class="section-header">{e(sec_title)}</li>\n')
        for art in articles:
            slug = slugify(art.get("title", ""), art_index)
            toc_items.append((slug, art.get("title", ""), sec_title))
            parts.append(f'  <li><a href="#{slug}">{e(art.get("title",""))}</a></li>\n')
            art_index += 1
    parts.append('</ul></div>\n')

    # ── SEKTIONER OCH ARTIKLAR ────────────────────────────────────────────────
    art_index = 0
    for sec_title, emoji, articles in sections:
        if not articles:
            continue

        parts.append(f"""<div class="section-divider">
  <h2>{emoji} {e(sec_title)}</h2>
</div>
""")
        for art in articles:
            slug    = slugify(art.get("title", ""), art_index)
            title   = e(art.get("title", ""))
            source  = e(art.get("source", ""))
            date    = e(art.get("date", ""))
            ingress = e(art.get("summary", ""))
            raw     = art.get("text", "") or ""

            if raw:
                body_parts = [
                    f"<p>{e(p.strip())}</p>"
                    for p in raw.split("\n\n")
                    if p.strip() and len(p.strip()) > 20
                ]
                body = "\n".join(body_parts) if body_parts else '<p class="no-text">Artikeltexten kunde inte hämtas.</p>'
            else:
                body = '<p class="no-text">Artikeltexten kunde inte hämtas.</p>'

            parts.append(f"""<div class="article" id="{slug}">
  <h2>{title}</h2>
  <p class="article-meta"><strong>{source}</strong> · {date}</p>
  {"<p class='article-ingress'>" + ingress + "</p>" if ingress else ""}
  {body}
  <p class="back-link"><a href="#top">↑ Tillbaka till innehållsförteckning</a></p>
</div>
""")
            art_index += 1

    parts.append("</body>\n</html>\n")

    with open(filename, "w", encoding="utf-8") as f:
        f.write("".join(parts))

    return filename
