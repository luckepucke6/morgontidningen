import html, re

CSS = """
body { font-family: Georgia, serif; line-height: 1.6; max-width: 800px; margin: auto; padding: 20px; color: #111; }
.cover { text-align: center; border-bottom: 2px solid #000; padding-bottom: 20px; margin-bottom: 30px; }
.ai-box { background: #f9f9f9; padding: 15px; border-left: 5px solid #333; margin: 20px 0; font-style: italic; }
.section-title { background: #333; color: #fff; padding: 10px; margin-top: 40px; text-transform: uppercase; }
.article { margin-bottom: 30px; border-bottom: 1px solid #eee; padding-bottom: 20px; }
h1, h2 { margin-bottom: 5px; }
.meta { font-size: 0.8em; color: #666; }
"""

def e(text): return html.escape(str(text or ""), quote=False)

def build_html(filename, cover_data, ai_summary, svt_nyheter, svt_sport, econ, world, science, tech):
    sections = [
        ("Nyheter", "📺", svt_nyheter),
        ("Ekonomi", "📈", econ),
        ("Utrikes", "🌍", world),
        ("Vetenskap", "🔭", science),
        ("Tech & AI", "💻", tech)
    ]

    parts = [f"<!DOCTYPE html><html><head><meta charset='utf-8'><style>{CSS}</style></head><body>"]
    
    # Framsida
    parts.append(f"<div class='cover'><h1>Morgontidningen</h1><p>{cover_data['weekday']} {cover_data['date']}</p>")
    parts.append(f"<p>Väder i {cover_data['weather_city']}: {cover_data['weather']['temp']}°C | USD/SEK: {cover_data['usd_sek']} kr</p></div>")
    
    parts.append(f"<div class='ai-box'><strong>Dagens översikt:</strong><br>{e(ai_summary)}</div>")

    for title, emoji, articles in sections:
        if not articles: continue
        parts.append(f"<h2 class='section-title'>{emoji} {title}</h2>")
        for art in articles:
            parts.append(f"<div class='article'><h3>{e(art['title'])}</h3>")
            parts.append(f"<p class='meta'>{art['source']} | {art['date']}</p>")
            parts.append(f"<p><strong>{e(art['summary'])}</strong></p>")
            parts.append(f"<p>{e(art['text'])}</p></div>")

    parts.append("</body></html>")
    with open(filename, "w", encoding="utf-8") as f: f.write("".join(parts))
