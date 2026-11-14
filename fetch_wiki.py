"""Parsiunčia kiekvienos places.txt vietos koordinates, Wikidata ID ir įžangą iš lt.wikipedia.

Naudojimas: python -I fetch_wiki.py <cache_dir>
Rezultatas: <cache_dir>/wiki.json  {straipsnis: {title, lat, lon, qid, extract, disambig}}
"""
import json, os, sys, time, urllib.error, urllib.parse, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(sys.argv[1], "wiki.json")
API = "https://lt.wikipedia.org/w/api.php"
UA = {"User-Agent": "geo-quiz-builder/1.0"}


def get(params):
    url = API + "?" + urllib.parse.urlencode({**params, "format": "json", "formatversion": "2"})
    while True:
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40) as r:
                time.sleep(3)
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code != 429:
                raise
            time.sleep(int(e.headers.get("retry-after", 30)) + 2)


titles = []
for line in open(os.path.join(HERE, "places.txt"), encoding="utf-8"):
    if line.strip() and not line.startswith("#"):
        titles.append(line.rstrip("\n").split("|")[4])

res = json.load(open(OUT, encoding="utf-8")) if os.path.exists(OUT) else {}
todo = [t for t in dict.fromkeys(titles) if t not in res]
for i in range(0, len(todo), 20):
    chunk = todo[i:i + 20]
    d = get({"action": "query", "titles": "|".join(chunk), "redirects": 1,
             "prop": "coordinates|pageprops|extracts", "coprimary": "primary", "colimit": "max",
             "exintro": 1, "explaintext": 1, "exlimit": "max", "ppprop": "wikibase_item|disambiguation"})
    q = d["query"]
    alias = {t: t for t in chunk}
    for key in ("normalized", "redirects"):
        for m in q.get(key, []):
            for t in chunk:
                if alias[t] == m["from"]:
                    alias[t] = m["to"]
    pages = {p["title"]: p for p in q["pages"]}
    for t in chunk:
        p = pages.get(alias[t], {})
        if p.get("missing") or not p:
            s = get({"action": "query", "list": "search", "srsearch": t, "srlimit": 5})
            res[t] = {"missing": True, "candidates": [x["title"] for x in s["query"]["search"]]}
            continue
        c = (p.get("coordinates") or [{}])[0]
        pp = p.get("pageprops", {})
        res[t] = {"title": p["title"], "lat": c.get("lat"), "lon": c.get("lon"),
                  "qid": pp.get("wikibase_item"), "disambig": "disambiguation" in pp,
                  "extract": (p.get("extract") or "")[:900]}
    time.sleep(0.5)
    json.dump(res, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

for t in dict.fromkeys(titles):
    r = res[t]
    if r.get("missing"):
        print("MISSING", t, "->", r["candidates"])
    elif r["disambig"]:
        print("DISAMBIG", t)
    elif r["lat"] is None:
        print("NOCOORD", t, r["qid"])
print(len(titles), "vietų,", sum(1 for t in titles if res[t].get("lat") is not None), "su koordinatėmis")

# Wikidata: koordinatės (P625) kryžminiam patikrinimui ir OSM ryšio ID (P402)
WD = os.path.join(sys.argv[1], "wikidata.json")
qids = sorted({r["qid"] for r in res.values() if r.get("qid")})
sparql = "SELECT ?item ?c ?osm WHERE { VALUES ?item { %s } OPTIONAL { ?item wdt:P625 ?c } OPTIONAL { ?item wdt:P402 ?osm } }" % " ".join("wd:" + q for q in qids)
req = urllib.request.Request("https://query.wikidata.org/sparql", headers={**UA, "Accept": "application/sparql-results+json"},
                             data=urllib.parse.urlencode({"query": sparql}).encode())
wd = {}
for b in json.load(urllib.request.urlopen(req, timeout=90))["results"]["bindings"]:
    q = b["item"]["value"].rsplit("/", 1)[1]
    e = wd.setdefault(q, {})
    if "c" in b and "lat" not in e:
        lon, lat = b["c"]["value"][6:-1].split()
        e["lat"], e["lon"] = float(lat), float(lon)
    if "osm" in b:
        e["osm"] = b["osm"]["value"]
json.dump(wd, open(WD, "w", encoding="utf-8"), indent=1)

import math
def km(a, b, c, d):
    p = math.pi / 180
    h = math.sin((c - a) * p / 2) ** 2 + math.cos(a * p) * math.cos(c * p) * math.sin((d - b) * p / 2) ** 2
    return 12742.0 * math.asin(math.sqrt(h))

for t in dict.fromkeys(titles):
    r, w = res[t], wd.get(res[t].get("qid"), {})
    if r.get("lat") is not None and "lat" in w:
        d = km(r["lat"], r["lon"], w["lat"], w["lon"])
        if d > 2:
            print("SKIRTUMAS %5.1f km  %s  wiki=%.4f,%.4f  wikidata=%.4f,%.4f" % (d, t, r["lat"], r["lon"], w["lat"], w["lon"]))
    elif r.get("lat") is None and not r.get("missing"):
        print("TIK WIKIDATA" if "lat" in w else "NĖRA KOORDINAČIŲ", t, w)
