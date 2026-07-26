# -*- coding: utf-8 -*-
from bs4 import BeautifulSoup
from pathlib import Path
import re, json
from urllib.parse import unquote, urlparse

html = Path(r"c:\Users\amaur\Downloads\Suicide Red.html").read_text(encoding="utf-8", errors="replace")
soup = BeautifulSoup(html, "html.parser")
out = Path("debug/_suicide_red_full_report.txt")
L = []
def p(s=""):
    L.append(s if isinstance(s, str) else str(s))

def meta(prop=None, name=None):
    t = soup.find("meta", property=prop) if prop else soup.find("meta", attrs={"name": name})
    return t.get("content") if t else None

p("=" * 72)
p("RAPPORT NAUTILJON — Suicide Red (dump local)")
p("=" * 72)

p()
p("## 1. Titres / Open Graph")
title = soup.find("title")
h1 = soup.find("h1")
p(f"title        : {title.get_text(strip=True) if title else None}")
p(f"h1           : {h1.get_text(' ', strip=True) if h1 else None}")
for prop in ["og:title", "og:image", "og:description", "og:url", "og:type"]:
    p(f"{prop:14}: {meta(prop=prop)}")

p()
p("## 2. Tous les <li> sous .infosFicheTop .liste_infos")
lis = soup.select(".infosFicheTop .liste_infos li")
p(f"Nombre: {len(lis)}")
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
    p(f"--- LI #{i} ---")
    p(f"  span label : {label!r}")
    p(f"  full text  : {full}")
    p(f"  links      : {links}")
    p(f"  itemprop   : {props}")

p()
p("## 3. .description")
desc = soup.select_one(".description")
p(f"present: {desc is not None}")
if desc:
    txt = " ".join(desc.get_text(" ", strip=True).split())
    p(f"len: {len(txt)}")
    p(f"first 300 chars:\n{txt[:300]}")

p()
p("## 4. Couvertures (sélecteurs)")
checks = [
    ("meta[property=og:image]", soup.find("meta", property="og:image")),
    ("#onglets_3_cover", soup.select_one("#onglets_3_cover")),
    ("img#onglets_3_cover", soup.select_one("img#onglets_3_cover")),
    (".image_fiche img", soup.select_one(".image_fiche img")),
    ("a.image_fiche img", soup.select_one("a.image_fiche img")),
    (".image_fiche a", soup.select_one(".image_fiche a")),
    ("img[itemprop=image]", soup.select_one("img[itemprop=image]")),
    ("img.cover", soup.select_one("img.cover")),
]
for name, el in checks:
    if el is None:
        p(f"  {name}: NO MATCH")
        continue
    url = el.get("content") or el.get("src") or el.get("href") or el.get("data-src")
    if not url:
        img = el.find("img") if hasattr(el, "find") else None
        if img:
            url = img.get("src") or img.get("data-src")
    p(f"  {name}: {url}")

p()
p("## 5. itemprop uniques (échantillon)")
props_map = {}
for el in soup.find_all(attrs={"itemprop": True}):
    ip = el.get("itemprop")
    sample = el.get("content") or el.get_text(strip=True)[:100]
    props_map.setdefault(ip, []).append({"tag": el.name, "sample": sample})
for ip, samples in sorted(props_map.items()):
    p(f"  {ip}: n={len(samples)} | ex={samples[0]}")

p()
p("## 6. Autres blocs métadonnées")
p("h2: " + " | ".join(h.get_text(strip=True) for h in soup.find_all("h2")))
p("h3: " + " | ".join(h.get_text(strip=True) for h in soup.find_all("h3")))
# Mot editeur
for h2 in soup.find_all("h2"):
    if "Mot" in h2.get_text():
        # sibling text
        parent = h2.parent
        txt = " ".join(h2.find_next().get_text(" ", strip=True).split())[:350]
        p(f"Mot de l'éditeur (extrait): {txt}")
# rating
rv = soup.select_one("[itemprop=ratingValue]")
rc = soup.select_one("[itemprop=ratingCount]")
p(f"Note: ratingValue={rv.get_text(strip=True) if rv else None} ratingCount={rc.get_text(strip=True) if rc else None}")
# keywords meta
p(f"meta keywords: {meta(name='keywords')}")
p(f"meta description: {meta(name='description')}")
# keywords search
for kw in ["Titre alternatif", "Titre original", "Titre VO", "Éditeur VO", "Editeur VO",
           "Nb volumes VO", "Année VO", "Annee VO", "Scénariste", "Dessinateur"]:
    p(f"  keyword '{kw}' in HTML: {kw in html or kw.lower() in html.lower()}")

# Simulate parse_nautiljon_html EXACTLY (mirror source)
p()
p("## PARSEUR WAYBACK (simulation exacte)")
title_p = None
og = soup.find("meta", property="og:title")
if og and og.get("content"):
    title_p = og["content"].strip()
summary = ""
desc_div = soup.find(class_="description")
if desc_div:
    for br in desc_div.find_all("br"):
        br.replace_with("\n")
    summary = desc_div.get_text(separator=" ", strip=True)
    summary = re.sub(r" +", " ", summary)
cover = None
og_img = soup.find("meta", property="og:image")
if og_img and og_img.get("content"):
    cover = og_img["content"].strip()
if not cover:
    img = soup.select_one("img#onglets_3_cover, img.cover, div.image_fiche img, a.image_fiche img")
    if img and img.get("src"):
        cover = img["src"].strip()

genres, tags, staff = [], [], []
year = None
pub_status = None
# Read exact theme/scenariste strings from source file
src = Path("debug/build_nautiljon_wayback.py").read_text(encoding="utf-8", errors="replace")
# extract the literal strings used in comparisons via running same unicode from file
# We'll duplicate the logic with unicode literals that match the SOURCE FILE content
m_theme = re.search(r'elif "([^"]+)" in label:\s*\n\s*tags', src)
m_scen = re.search(r'"Auteur" in label or "([^"]+)" in label', src)
theme_lit = m_theme.group(1) if m_theme else "Thème"
scen_lit = m_scen.group(1) if m_scen else "Scénariste"
p(f"Source litérale Thème: {theme_lit!r} codepoints={[hex(ord(c)) for c in theme_lit]}")
p(f"Source litérale Scénariste: {scen_lit!r}")

infos = soup.find(class_="infosFicheTop")
liste = infos.find(class_="liste_infos") if infos else None
for li in (liste.find_all("li") if liste else []):
    text_li = li.get_text(separator=" ", strip=True)
    span = li.find("span")
    if not span:
        continue
    label = span.get_text(strip=True)
    matched = []
    if "Genre" in label:
        genres = [a.get_text(strip=True) for a in li.find_all("a")]
        matched.append("genres")
    elif theme_lit in label:
        tags = [a.get_text(strip=True) for a in li.find_all("a")]
        matched.append("tags/theme")
    elif "Origine" in label:
        year_tag = li.find(itemprop="datePublished")
        if year_tag and year_tag.has_attr("content"):
            try:
                year = int(year_tag["content"])
            except Exception:
                pass
        if year is None:
            m = re.search(r"(19|20)\d{2}", text_li)
            if m:
                year = int(m.group(0))
        matched.append(f"origine/year={year}")
    elif "Auteur" in label or scen_lit in label:
        for a in li.find_all("a"):
            name = a.get_text(strip=True)
            if name:
                staff.append({"role": "Story", "name": name})
        matched.append("auteur")
    elif "Dessinateur" in label:
        for a in li.find_all("a"):
            name = a.get_text(strip=True)
            if name:
                staff.append({"role": "Art", "name": name})
        matched.append("dessinateur")
    elif "Nb volumes VO" in label or "Nb volumes" in label:
        if "(Terminé)" in text_li:
            pub_status = "FINISHED"
        elif "(En cours)" in text_li:
            pub_status = "RELEASING"
        elif "(En attente)" in text_li:
            pub_status = "HIATUS"
        elif "(Abandonné)" in text_li:
            pub_status = "CANCELLED"
        matched.append(f"volumes/status={pub_status}")
    p(f"  label={label!r} -> matched={matched or ['(rien)']}")

result = {
    "title": title_p,
    "summary_len": len(summary),
    "summary_preview": summary[:180],
    "cover_url": cover,
    "year": year,
    "pub_status": pub_status,
    "genres": genres,
    "tags": tags,
    "staff": staff,
}
p()
p("Résultat parse_nautiljon_html:")
p(json.dumps(result, ensure_ascii=False, indent=2))

p()
p("## COMPARAISON MetaKavita")
p("Extrait par le parseur:")
p("  - title (og:title)")
p("  - summary (.description)")
p("  - cover_url (og:image / fallbacks)")
p("  - genres (label contenant Genre)")
p("  - tags (label Thème)")
p("  - year (Origine + datePublished ou regex année)")
p("  - staff Story (Auteur/Scénariste) + Art (Dessinateur)")
p("  - pub_status via Nb volumes [VO]")
p()
p("Présent sur la page mais NON extrait (priorisé):")
gaps = [
    ("HAUTE", "Éditeur VF", "Ki-oon", "Publisher Kavita — critique pour MetaKavita"),
    ("HAUTE", "Type", "Shonen", "Demographic / format series"),
    ("HAUTE", "Année VF", "2026", "Year: Origine n'a pas d'année ici → year=null actuellement"),
    ("HAUTE", "Nb volumes VF (count)", "1", "Seule la présence de statut est lue; le nombre de volumes n'est pas stocké"),
    ("MOYENNE", "Âge conseillé", "12 ans et +", "Age rating Kavita"),
    ("MOYENNE", "Origine (pays)", "Japon", "Seul le year est lu; le pays n'est pas stocké"),
    ("MOYENNE", "aggregateRating", "9/10 (3)", "Community score"),
    ("MOYENNE", "Mot de l'éditeur", "texte promo Ki-oon", "Blurbs alternatif / marketing copy"),
    ("BASSE", "Dernier paru / À paraître", "02/07/2026 / 01/10/2026", "Dates de sortie volumes"),
    ("BASSE", "Prix", "7.95 €", "Peu utile MetaKavita"),
    ("BASSE", "og:url / og:description", "présents", "URL canonique; desc déjà couverte via .description"),
    ("N/A page", "Titre alternatif / Titre VO", "absent", "Pas sur cette fiche"),
    ("N/A page", "Éditeur VO / Nb volumes VO / Année VO / Dessinateur", "absent", "Fiche orientée VF (licence FR récente)"),
]
for pri, field, val, why in gaps:
    p(f"  [{pri}] {field} = {val!r} — {why}")

out.write_text("\n".join(L), encoding="utf-8")
print(f"Wrote {out} ({len(L)} lines)")
