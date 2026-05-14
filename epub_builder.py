"""
epub_builder.py – Bygger EPUB-filen för Morgontidningen
Optimerad för Kobo Libra Colour.
"""

import re
import html as html_module
from ebooklib import epub

# ── CSS – anpassad för Kobo Libra Colour ─────────────────────────────────────
CSS = """
@charset "UTF-8";

body {
    font-family: Georgia, "Times New Roman", serif;
    font-size: 1em;
    line-height: 1.7;
    margin: 1.2em 1.4em;
    color: #111;
    background: #fff;
}

h1 { font-size: 1.9em; margin: 0.4em 0 0.2em; line-height: 1.2; }
h2 { font-size: 1.4em; margin: 0.8em 0 0.3em; line-height: 1.3; }
h3 { font-size: 1.1em; font-weight: bold; color: #333; margin: 0.5em 0; }
p  { margin: 0.5em 0; orphans: 2; widows: 2; }
em { font-style: italic; }
hr { border: none; border-top: 1px solid #ccc; margin: 1.5em 0; }

/* ── Framsida ── */
.cover        { text-align: center; padding: 2em 0.5em; }
.cover-title  {
    font-size: 2.4em;
    letter-spacing: 0.06em;
    border-bottom: 3px double #222;
    padding-bottom: 0.4em;
    margin-bottom: 0.3em;
}
.cover-date   { font-size: 0.95em; color: #555; margin-bottom: 1.8em; }

.meta-table   { width: 100%; border-collapse: collapse; margin: 1em 0 1.8em; }
.meta-table td {
    padding: 0.45em 0.5em;
    border-bottom: 1px solid #e0e0e0;
    font-size: 0.95em;
}
.meta-label   { font-weight: bold; text-align: left; width: 55%; }
.meta-value   { text-align: right; color: #333; }

.ai-box {
    border: 1px solid #bbb;
    border-left: 4px solid #555;
    padding: 0.8em 1em;
    margin: 1.2em 0;
    font-style: italic;
    background: #fafafa;
}
.ai-box-title { font-style: normal; font-weight: bold; font-size: 0.9em;
                text-transform: uppercase; letter-spacing: 0.05em;
                color: #555; margin-bottom: 0.4em; }

/* ── Sektionssida ── */
.section-page {
    text-align: center;
    padding: 3em 1em;
    page-break-before: always;
}
.section-emoji { font-size: 2.5em; display: block; margin-bottom: 0.3em; }
.section-title {
    font-size: 2em;
    border-top: 2px solid #333;
    border-bottom: 2px solid #333;
    padding: 0.3em 0;
    margin: 0;
}
.section-count { font-size: 0.85em; color: #777; margin-top: 0.5em; }

/* ── Artikel ── */
.article-meta {
    font-size: 0.82em;
    color: #666;
    margin-bottom: 0.9em;
    border-bottom: 1px solid #eee;
    padding-bottom: 0.4em;
}
.article-score { float: right; color: #999; }
.ingress { font-style: italic; color: #333; margin-bottom: 1em; border-left: 3px solid #ccc; padding-left: 0.7em; }
.no-text { color: #888; font-style: italic; }
"""


# ── Hjälpfunktioner ───────────────────────────────────────────────────────────
def clean(text: str) -> str:
    """Strip HTML tags, collapse whitespace, and escape XML special chars."""
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    text = text.strip()
    return html_module.escape(text)

def clean_body(text: str) -> str:
    """Clean body paragraph text — strip tags but keep & escaped."""
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return html_module.escape(text.strip())


FALLBACK_HTML = """<?xml version='1.0' encoding='utf-8'?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="sv">
<head><meta charset="utf-8"/><title>Sida</title></head>
<body><p>Innehåll saknas.</p></body>
</html>"""

def make_chapter(uid: str, title: str, content: str, style_item) -> epub.EpubHtml:
    safe_content = content.strip() if content and content.strip() else FALLBACK_HTML
    ch = epub.EpubHtml(
        uid=uid,
        title=(title or "Artikel")[:80],
        file_name=f"{uid}.xhtml",
        lang="sv",
    )
    ch.content = safe_content
    ch.add_item(style_item)
    return ch


def article_html(uid: str, article: dict) -> str:
    title   = clean(article.get("title", "") or "")
    summary = clean(article.get("summary", "") or "")
    raw     = article.get("text", "") or ""
    source  = html_module.escape(article.get("source", "") or "")
    date    = html_module.escape(str(article.get("date", "") or ""))
    score   = article.get("score", "")

    score_badge = f'<span class="article-score">{score}/10</span>' if score and score != 10 else ""

    ingress = (f'<p class="ingress">{summary}</p>' if summary else "")

    if raw:
        body = "".join(
            f"<p>{clean_body(p)}</p>"
            for p in raw.split("\n\n")
            if p.strip() and len(p.strip()) > 20
        )
    else:
        body = '<p class="no-text">Artikeltexten kunde inte hämtas.</p>'

    return f"""<?xml version='1.0' encoding='utf-8'?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="sv">
<head>
  <meta charset="utf-8"/>
  <title>{title}</title>
  <link rel="stylesheet" href="../style/main.css"/>
</head>
<body>
  <h2>{title}</h2>
  <p class="article-meta">{score_badge}<strong>{source}</strong> · {date}</p>
  {ingress}
  {body}
</body>
</html>"""


def section_html(title: str, emoji: str, count: int) -> str:
    noun = "artikel" if count == 1 else "artiklar"
    return f"""<?xml version='1.0' encoding='utf-8'?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="sv">
<head>
  <meta charset="utf-8"/>
  <title>{title}</title>
  <link rel="stylesheet" href="../style/main.css"/>
</head>
<body>
  <div class="section-page">
    <span class="section-emoji">{emoji}</span>
    <h1 class="section-title">{title}</h1>
    <p class="section-count">{count} {noun}</p>
  </div>
</body>
</html>"""


# ── Huvudfunktion ─────────────────────────────────────────────────────────────
def build_epub(
    filename: str,
    cover_data: dict,
    ai_summary: str,
    svt_nyheter: list,
    svt_sport: list,
    nt_articles: list,
    tech_articles: list,
):
    book = epub.EpubBook()
    book.set_identifier(f"morgontidningen-{cover_data.get('date','')}")
    book.set_title(f"Morgontidningen {cover_data.get('date','')}")
    book.set_language("sv")
    book.add_author("Morgontidningen")

    # CSS
    style = epub.EpubItem(
        uid="main_css",
        file_name="style/main.css",
        media_type="text/css",
        content=CSS,
    )
    book.add_item(style)

    # ── Framsida ──────────────────────────────────────────────────────────
    w  = cover_data.get("weather", {})
    total = len(svt_nyheter) + len(svt_sport) + len(nt_articles) + len(tech_articles)
    safe_summary = html_module.escape(ai_summary or "")
    safe_weekday = html_module.escape(str(cover_data.get('weekday','')))
    safe_date    = html_module.escape(str(cover_data.get('date','')))
    safe_week    = html_module.escape(str(cover_data.get('week','')))
    safe_nameday = html_module.escape(str(cover_data.get('nameday','–')))
    safe_temp    = html_module.escape(str(w.get('temp','?')))
    safe_desc    = html_module.escape(str(w.get('desc','')))
    safe_usd     = html_module.escape(str(cover_data.get('usd_sek','?')))

    cover_content = f"""<?xml version='1.0' encoding='utf-8'?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="sv">
<head>
  <meta charset="utf-8"/>
  <title>Framsida</title>
  <link rel="stylesheet" href="style/main.css"/>
</head>
<body>
  <div class="cover">
    <h1 class="cover-title">Morgontidningen</h1>
    <p class="cover-date">
      {safe_weekday} {safe_date} · Vecka {safe_week}
    </p>

    <div class="ai-box">
      <p class="ai-box-title">Dagens översikt</p>
      <p>{safe_summary}</p>
    </div>

    <table class="meta-table">
      <tr><td class="meta-label">🎂 Namnsdag</td>
          <td class="meta-value">{safe_nameday}</td></tr>
      <tr><td class="meta-label">🌤 Väder Norrköping</td>
          <td class="meta-value">{safe_temp}°C · {safe_desc}</td></tr>
      <tr><td class="meta-label">💵 USD/SEK</td>
          <td class="meta-value">{safe_usd} kr</td></tr>
      <tr><td class="meta-label">📰 Artiklar idag</td>
          <td class="meta-value">{total} st</td></tr>
    </table>
  </div>
</body>
</html>"""

    cover_ch = make_chapter("cover", "Framsida", cover_content, style)
    book.add_item(cover_ch)

    spine = ["nav", cover_ch]
    toc   = [epub.Link("cover.xhtml", "Framsida", "cover")]

    # ── Sektioner ─────────────────────────────────────────────────────────
    sections = [
        ("SVT Nyheter", "📺", svt_nyheter),
        ("SVT Sport",   "⚽", svt_sport),
        ("NT Sport",    "🏈", nt_articles),
        ("Tech & AI",   "💻", tech_articles),
    ]

    for sec_title, emoji, articles in sections:
        if not articles:
            continue

        sec_id = sec_title.lower().replace(" ", "_").replace("&", "och")

        # Sektionsavdelare
        div_ch = make_chapter(
            f"sec_{sec_id}",
            sec_title,
            section_html(sec_title, emoji, len(articles)),
            style,
        )
        book.add_item(div_ch)
        spine.append(div_ch)

        # Artikelkapitel
        art_toc = []
        for i, article in enumerate(articles):
            uid = f"{sec_id}_{i}"
            ch  = make_chapter(uid, article["title"], article_html(uid, article), style)
            book.add_item(ch)
            spine.append(ch)
            art_toc.append(epub.Link(f"{uid}.xhtml", article["title"][:70], uid))

        toc.append((epub.Section(sec_title), art_toc))

    # ── Navigering ────────────────────────────────────────────────────────
    book.toc   = toc
    book.spine = spine
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())

    epub.write_epub(filename, book)
