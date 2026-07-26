from bs4 import BeautifulSoup
from pathlib import Path

html_path = Path(r"c:\Users\amaur\Downloads\Suicide Red.html")
out_path = Path(r"debug\_suicide_red_parse_report.txt")
soup = BeautifulSoup(html_path.read_text(encoding="utf-8", errors="replace"), "html.parser")
lines = []

def p(s=""):
    lines.append(s)

def meta(prop=None, name=None):
    t = soup.find("meta", property=prop) if prop else soup.find("meta", attrs={"name": name})
    return t.get("content") if t else None

p("=" * 70)
p("1. TITRES / OPEN GRAPH")
p("=" * 70)
h1 = soup.find("h1")
title = soup.find("title")
p(f"title: {title.get_text(strip=True) if title else None}")
p(f"h1: {h1.get_text(strip=True) if h1 else None}")
for prop in ["og:title", "og:image", "og:description", "og:url", "og:type", "og:site_name"]:
    p(f"{prop}: {meta(prop=prop)}")

p()
p("=" * 70)
p("2. EVERY li sous .infosFicheTop .liste_infos")
p("=" * 70)
lis = soup.select(".infosFicheTop .liste_infos li")
p(f"count: {len(lis)}")
for i, li in enumerate(lis, 1):
    span = li.find("span")
    label = span.get_text(strip=True) if span else None
    full = " ".join(li.get_text(" ", strip=True).split())
    links = [(a.get_text(strip=True), a.get("href")) for a in li.find_all("a")]
    props = []
    for el in li.find_all(True):
        if el.has_attr("itemprop"):
            props.append({
                "tag": el.name,
                "itemprop": el.get("itemprop"),
                "content": el.get("content"),
                "text": el.get_text(strip=True)[:120],
            })
        elif el.has_attr("content"):
            props.append({
                "tag": el.name,
                "content_only": el.get("content"),
                "attrs": {k: v for k, v in el.attrs.items() if k in ("datetime", "content", "class")},
            })
    p(f"--- LI #{i} ---")
    p(f"  label: {label}")
    p(f"  full: {full}")
    p(f"  links: {links}")
    p(f"  itemprop/content: {props}")

p()
p("=" * 70)
p("3. .description")
p("=" * 70)
desc = soup.select_one(".description")
p(f"presence: {desc is not None}")
if desc:
    txt = " ".join(desc.get_text(" ", strip=True).split())
    p(f"len: {len(txt)}")
    p(f"first300: {txt[:300]}")

p()
p("=" * 70)
p("4. COVER SELECTORS")
p("=" * 70)
checks = [
    ("meta og:image", soup.find("meta", property="og:image")),
    ("#onglets_3_cover", soup.select_one("#onglets_3_cover")),
    ("#onglets_3_cover img", soup.select_one("#onglets_3_cover img")),
    (".image_fiche img", soup.select_one(".image_fiche img")),
    (".image_fiche a", soup.select_one(".image_fiche a")),
    ("img[itemprop=image]", soup.select_one("img[itemprop=image]")),
    ("meta[itemprop=image]", soup.find("meta", itemprop="image")),
]
for name, el in checks:
    if el is None:
        p(f"{name}: NO MATCH")
        continue
    url = el.get("content") or el.get("src") or el.get("href") or el.get("data-src")
    if not url and el.name != "img":
        img = el.find("img")
        if img:
            url = img.get("src") or img.get("data-src")
    p(f"{name}: MATCH -> {url}")

p("extra cover-ish:")
for img in soup.select("img"):
    src = img.get("src") or ""
    alt = img.get("alt") or ""
    if any(k in (src + alt).lower() for k in ["cover", "couverture", "fiche", "jaquette"]):
        p(f"  src={src} alt={alt[:80]}")

p()
p("=" * 70)
p("5. UNIQUE itemprop VALUES (sample)")
p("=" * 70)
props_map = {}
for el in soup.find_all(attrs={"itemprop": True}):
    ip = el.get("itemprop")
    sample = el.get("content") or el.get_text(strip=True)[:100]
    props_map.setdefault(ip, []).append({"tag": el.name, "sample": sample, "content": el.get("content")})
for ip, samples in sorted(props_map.items()):
    p(f"{ip}: n={len(samples)} sample={samples[0]}")

p()
p("=" * 70)
p("6. OTHER METADATA BLOCKS")
p("=" * 70)
for sel in [".notes", "#notes", ".note", ".infosFicheBottom", ".liste_infos", "h2", "h3", ".onglets", "#onglets", ".personnages", ".characters", ".censure"]:
    els = soup.select(sel)
    if els:
        p(f"{sel}: {len(els)} match(es)")
        for el in els[:8]:
            t = " ".join(el.get_text(" ", strip=True).split())[:180]
            p(f"  -> {t}")

p("ALL h2:")
for h in soup.find_all("h2"):
    p(f"  {h.get_text(strip=True)[:150]}")
p("ALL h3:")
for h in soup.find_all("h3"):
    p(f"  {h.get_text(strip=True)[:150]}")

p("infosFicheBottom / other liste_infos:")
for li in soup.select(".infosFicheBottom li, .infosFicheBottom .liste_infos li"):
    p(f"  {' '.join(li.get_text(' ', strip=True).split())[:220]}")

p("ALL .liste_infos li labels site-wide:")
for li in soup.select(".liste_infos li"):
    span = li.find("span")
    lab = span.get_text(strip=True) if span else "?"
    full = " ".join(li.get_text(" ", strip=True).split())[:200]
    p(f"  [{lab}] {full}")

for sel in [".rate", ".rating", ".note_moyenne", ".stats", ".infos_stats", "[itemprop=aggregateRating]", ".moyenne", "#fiche_rating", ".stars"]:
    els = soup.select(sel)
    if els:
        for el in els[:3]:
            p(f"{sel}: {' '.join(el.get_text(' ', strip=True).split())[:220]}")

for s in soup.find_all("script", type="application/ld+json"):
    p("JSON-LD: " + (s.string[:800] if s.string else "None"))

p()
p("ALL meta name/property:")
for m in soup.find_all("meta"):
    if m.get("property") or m.get("name"):
        p(f"  {m.get('property') or m.get('name')}: {m.get('content')}")

out_path.write_text("\n".join(lines), encoding="utf-8")
print(f"WROTE {out_path} lines={len(lines)}")
