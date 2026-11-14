"""Iš parsiųstų atvirų duomenų surenka žaidimo duomenis, juos patikrina ir įrašo į kur-lietuvoje.html.

Naudojimas: python -I build_data.py <raw_dir> [preview.svg]
Šaltiniai (raw_dir): OSM (Nominatim/Overpass) – siena, pakrantė, apskritys, upės, ežerai, parkai;
Natural Earth – kaimyninių šalių tarpusavio sienos; lt.wikipedia/Wikidata – vietų koordinatės;
GeoNames – miestų koordinačių kryžminis patikrinimas.
"""
import json, math, os, re, sys

from shapely.geometry import LineString, MultiLineString, MultiPolygon, Point, Polygon, box, shape
from shapely.ops import linemerge, polygonize, unary_union

RAW = sys.argv[1]
HERE = os.path.dirname(os.path.abspath(__file__))
J = lambda *p: json.load(open(os.path.join(RAW, *p), encoding="utf-8"))

# ---------- LKS-94 (skersinė Merkatoriaus, GRS80, 24° r. ilg., k0 = 0,9998) ----------
n = (1 / 298.257222101) / (2 - 1 / 298.257222101)
KA = 0.9998 * 6378137.0 / (1 + n) * (1 + n * n / 4 + n ** 4 / 64)
AL = [n / 2 - 2 * n * n / 3 + 5 * n ** 3 / 16, 13 * n * n / 48 - 3 * n ** 3 / 5, 61 * n ** 3 / 240]
BE = [n / 2 - 2 * n * n / 3 + 37 * n ** 3 / 96, n * n / 48 + n ** 3 / 15, 17 * n ** 3 / 480]
DE = [2 * n - 2 * n * n / 3 - 2 * n ** 3, 7 * n * n / 3 - 8 * n ** 3 / 5, 56 * n ** 3 / 15]
CN = 2 * math.sqrt(n) / (1 + n)
E0, N0, U = 200000.0, 6370000.0, 20.0  # žemėlapio pradžia (LKS-94 m) ir kvantavimo žingsnis
BW, BH = 600000.0, 510000.0  # duomenų stačiakampis metrais


def lks(lon, lat):
    phi, dl = math.radians(lat), math.radians(lon - 24)
    t = math.sinh(math.atanh(math.sin(phi)) - CN * math.atanh(CN * math.sin(phi)))
    xi, eta = math.atan2(t, math.cos(dl)), math.atanh(math.sin(dl) / math.sqrt(1 + t * t))
    e, nn = eta, xi
    for j in (1, 2, 3):
        e += AL[j - 1] * math.cos(2 * j * xi) * math.sinh(2 * j * eta)
        nn += AL[j - 1] * math.sin(2 * j * xi) * math.cosh(2 * j * eta)
    return 500000 + KA * e, KA * nn


def lks_inv(e, nn):
    xi, eta = nn / KA, (e - 500000) / KA
    x, y = xi, eta
    for j in (1, 2, 3):
        x -= BE[j - 1] * math.sin(2 * j * xi) * math.cosh(2 * j * eta)
        y -= BE[j - 1] * math.cos(2 * j * xi) * math.sinh(2 * j * eta)
    chi = math.asin(math.sin(x) / math.cosh(y))
    phi = chi + sum(DE[j - 1] * math.sin(2 * j * chi) for j in (1, 2, 3))
    return 24 + math.degrees(math.atan2(math.sinh(y), math.cos(x))), math.degrees(phi)


def P(lon, lat):  # geografinės -> žemėlapio metrai (x į rytus, y žemyn)
    e, nn = lks(lon, lat)
    return e - E0, N0 - nn


def proj(geom):  # GeoJSON geometrija -> shapely žemėlapio metrais
    def ring(c):
        return [P(x, y) for x, y in c]
    t, c = geom["type"], geom["coordinates"]
    if t == "Polygon":
        return Polygon(ring(c[0]))  # skyles (salas) ignoruojame
    if t == "MultiPolygon":
        return unary_union([Polygon(ring(p[0])).buffer(0) for p in c])
    if t == "LineString":
        return LineString(ring(c))
    if t == "MultiLineString":
        return MultiLineString([ring(l) for l in c])
    raise ValueError(t)


def hav(a, b, c, d):
    p = math.pi / 180
    h = math.sin((c - a) * p / 2) ** 2 + math.cos(a * p) * math.cos(c * p) * math.sin((d - b) * p / 2) ** 2
    return 12742.0 * math.asin(math.sqrt(h))


def enc(coords):  # delta kodavimas U metrų žingsniu
    out, px, py = [], 0, 0
    for x, y in coords:
        qx, qy = round(x / U), round(y / U)
        if out and qx == px and qy == py:
            continue
        out += [qx - px, qy - py]
        px, py = qx, qy
    return out


def polys(g):
    if g.is_empty:
        return []
    if g.geom_type == "Polygon":
        return [g]
    return [p for p in getattr(g, "geoms", []) for p in polys(p)]


def lines(g):
    if g.is_empty:
        return []
    if g.geom_type == "LineString":
        return [g]
    return [l for p in getattr(g, "geoms", []) for l in lines(p)]


BOX = box(0, 0, BW, BH)

# ---------- sausuma ir jūra iš OSM pakrantės ----------
coast = [LineString([P(p["lon"], p["lat"]) for p in w["geometry"]]) for w in J("coastwide", "coast.json")["elements"]]
coast = unary_union(coast).intersection(BOX.buffer(1))
faces = list(polygonize(unary_union([coast, BOX.boundary])))
SEA_PTS = [(20.0, 55.8), (23.6, 57.3), (21.1, 55.3), (19.4, 54.6)]
sea_pts = [Point(P(*p)) for p in SEA_PTS]
land_mask = unary_union([f for f in faces if not any(f.contains(p) for p in sea_pts)])
# Aistmarės OSM pažymėtos ne pakrante, o atskiru poligonu
land_mask = land_mask.difference(proj(J("vistula", "v.geojson")["features"][0]["geometry"]).buffer(0))
assert land_mask.contains(Point(P(25.28, 54.69))), "Vilnius turi būti sausumoje"
assert not land_mask.contains(Point(P(21.1, 55.3))), "Kuršių marios turi būti vanduo"

LT_ADMIN = proj(J("lt", "lt.geojson")["features"][0]["geometry"]).buffer(0)
LT_LAND = LT_ADMIN.intersection(land_mask)

# topologiškai suderintas supaprastinimas: viena linijų aibė -> poligonai
work = unary_union([land_mask.boundary, LT_ADMIN.boundary.intersection(land_mask)])
merged = lines(linemerge(work))
near = LT_LAND.buffer(3000)
simp, border_lines, coast_lines = [], [], []
for l in merged:
    s = l.simplify(70 if l.intersects(near) else 300)
    simp.append(s)
    if l.intersects(near):
        mid = l.interpolate(0.5, normalized=True)
        on_box = BOX.boundary.distance(mid) < 1
        (border_lines if LT_ADMIN.boundary.distance(mid) < 1 else coast_lines if not on_box else []).append(s)
lt_faces, foreign_faces = [], []
for f in polygonize(unary_union(simp)):
    rp = f.representative_point()
    if not land_mask.buffer(200).contains(rp):
        continue
    if LT_ADMIN.contains(rp):
        if f.area > 0.15e6:
            lt_faces.append(f)
    elif f.area > 1.5e6:
        foreign_faces.append(f)
LT_SIMPLE = unary_union(lt_faces)

# ---------- apskričių vidinės ribos ----------
counties = [proj(f["geometry"]).buffer(0) for f in J("counties", "counties.geojson")["features"]]
assert len(counties) == 10
inner = unary_union([c.boundary for c in counties]).difference(LT_ADMIN.boundary.buffer(40)).intersection(LT_LAND)
county_lines = [l.simplify(150) for l in lines(linemerge(inner)) if l.length > 1500]

# ---------- kaimynų tarpusavio sienos (Natural Earth) ----------
ne = []
foreign = unary_union(foreign_faces)
for f in J("ne", "boundary_lines.geojson")["features"]:
    pr = f["properties"]
    if "LTU" in (pr.get("ADM0_A3_L"), pr.get("ADM0_A3_R")):
        continue
    g = shape(f["geometry"])
    if not g.intersects(box(18, 52, 30, 58.5)):
        continue
    for l in lines(g):
        pl = LineString([P(x, y) for x, y in l.coords]).intersection(foreign)
        ne += [s.simplify(400) for s in lines(pl) if s.length > 3000]

# ---------- upės ----------
RIVER_FILES = ["nemunas", "neris", "sventoji", "venta", "nevezis", "more"]
rel_ways = {}
for fn in RIVER_FILES:
    for el in J("rivers", fn + ".json")["elements"]:
        rel_ways[el["id"]] = [LineString([P(p["lon"], p["lat"]) for p in m["geometry"]])
                              for m in el["members"]
                              if m["type"] == "way" and m.get("geometry") and m.get("role", "") in ("", "main_stream")
                              and len(m["geometry"]) > 1]
river_clip = LT_ADMIN.buffer(400).intersection(BOX)


def river(rel_id):
    g = linemerge(unary_union(rel_ways[rel_id])).intersection(river_clip)
    ls = [l.simplify(90) for l in lines(linemerge(g) if g.geom_type != "LineString" else g)]
    longest = max(l.length for l in ls)
    return [l for l in ls if l.length > min(3000, longest / 2)]


# ---------- vietos ----------
wiki, wd, sel = J("wiki", "wiki.json"), J("wiki", "wikidata.json"), J("features", "sel.json")
area_geo = {}
for fn in ("areas1.geojson", "areas2.geojson"):
    for f in J("features", fn)["features"]:
        area_geo[(f["properties"]["osm_type"][0], f["properties"]["osm_id"])] = f["geometry"]


def area(name):
    s = sel[name]
    g = proj(area_geo[("r", s["rel"]) if "rel" in s else ("w", s["way"])]).buffer(0).intersection(BOX)
    ps = polys(g)
    big = max(p.area for p in ps)
    out = []
    for p in ps:
        if p.area >= 0.03 * big:
            q = Polygon(p.exterior).simplify(min(150, max(25, math.sqrt(p.area) * 0.012)))
            out += polys(q.buffer(0))
    return out


places, shapes, problems, notes = [], [], [], []
names = set()
for line in open(os.path.join(HERE, "places.txt"), encoding="utf-8"):
    if not line.strip() or line.startswith("#"):
        continue
    f = line.rstrip("\n").split("|")
    cat, diff, kind, name, title, verb, fact = f[:7]
    if name in names:
        problems.append("dublikatas: " + name)
    names.add(name)
    if not fact.strip():
        problems.append("nėra fakto: " + name)
    w = wiki[title]
    src = "lt.wikipedia"
    lat, lon = w.get("lat"), w.get("lon")
    if lat is None and "lat" in wd.get(w.get("qid"), {}):
        lat, lon, src = wd[w["qid"]]["lat"], wd[w["qid"]]["lon"], "Wikidata"
    if len(f) > 7:
        lat, lon = map(float, f[7][1:].split(","))
        src = "OSM"
    shape_i, radius = -1, 0
    if kind == "a":
        ps = area(name)
        u = unary_union(ps)
        if not u.intersects(LT_ADMIN):
            problems.append("plotas ne Lietuvoje: " + name)
        pt = Point(P(lon, lat)) if lat is not None else None
        if pt is None or not u.contains(pt):
            rp = max(ps, key=lambda p: p.area).intersection(LT_ADMIN.buffer(1)).representative_point()
            lon, lat = lks_inv(rp.x + E0, N0 - rp.y)
            src = "OSM"
        shapes.append({"t": "a", "g": [enc(p.exterior.coords) for p in ps]})
        shape_i = len(shapes) - 1
    elif kind == "l":
        ls = river(sel[name]["rel"])
        inside = sum(l.intersection(LT_ADMIN.buffer(400)).length for l in ls) / 1000
        if inside < 20:
            problems.append("upės ilgis Lietuvoje per mažas: %s %.0f km" % (name, inside))
        notes.append("upė %-10s %4.0f km vagos, %d atkarpos" % (name, inside, len(ls)))
        mid = max(ls, key=lambda l: l.length).interpolate(0.5, normalized=True)
        lon, lat = lks_inv(mid.x + E0, N0 - mid.y)
        src = "OSM"
        shapes.append({"t": "l", "g": [enc(l.coords) for l in ls]})
        shape_i = len(shapes) - 1
    else:
        if lat is None:
            problems.append("nėra koordinačių: " + name)
            continue
        if kind[0] == "r":
            radius = int(kind[1:])
        d = LT_LAND.distance(Point(P(lon, lat)))
        if d > 0:
            notes.append("už sausumos kontūro %4.0f m: %s" % (d, name))
        if d > 600:
            problems.append("taškas ne Lietuvoje: %s (%.1f km)" % (name, d / 1000))
    places.append({"n": name, "c": cat, "d": int(diff), "k": kind[0], "v": verb, "f": fact,
                   "lat": round(lat, 5), "lon": round(lon, 5), "s": shape_i, "r": radius, "src": src})

# ---------- patikros ----------
by = {p["n"]: p for p in places}
pts = [p for p in places if p["k"] in "pr"]
for i, a in enumerate(pts):
    for b in pts[i + 1:]:
        if hav(a["lat"], a["lon"], b["lat"], b["lon"]) < 0.15:
            problems.append("sutampa koordinatės: %s / %s" % (a["n"], b["n"]))
for a, b, exp, tol in (("Vilnius", "Kaunas", 92, 4), ("Vilnius", "Klaipėda", 290, 6)):
    d = hav(by[a]["lat"], by[a]["lon"], by[b]["lat"], by[b]["lon"])
    pa, pb = P(by[a]["lon"], by[a]["lat"]), P(by[b]["lon"], by[b]["lat"])
    dp = math.hypot(pa[0] - pb[0], pa[1] - pb[1]) / 1000
    notes.append("%s–%s: haversine %.1f km, projekcijoje %.1f km (laukta ~%d)" % (a, b, d, dp, exp))
    # haversine skaičiuoja rutuliu (R = 6371 km), LKS-94 – elipsoidu, todėl ~0,3 % skirtumas yra lauktinas
    if abs(d - exp) > tol or abs(dp - d) / d > 0.005:
        problems.append("atstumas %s–%s nesutampa" % (a, b))
for lon, lat in ((21.0, 55.3), (24.0, 54.0), (26.8, 55.7), (25.28, 54.69)):
    lo, la = lks_inv(*lks(lon, lat))
    assert abs(lo - lon) < 1e-8 and abs(la - lat) < 1e-8
try:
    import pyproj
    tr = pyproj.Transformer.from_crs(4326, 3346, always_xy=True)
    err = max(math.hypot(*(a - b for a, b in zip(lks(lo, la), tr.transform(lo, la))))
              for lo, la in ((21.0, 55.3), (24.0, 54.0), (26.8, 55.7), (25.28, 54.69)))
    notes.append("LKS-94 prieš pyproj EPSG:3346: didžiausia paklaida %.4f m" % err)
    if err > 0.01:
        problems.append("LKS-94 projekcija nesutampa su pyproj")
except ImportError:
    notes.append("pyproj nėra – projekcija su EPSG:3346 nepalyginta")

gn = {}
for row in open(os.path.join(RAW, "geonames", "LT.txt"), encoding="utf-8"):
    c = row.split("\t")
    if c[6] == "P":
        for nm in {c[1], *c[3].split(",")}:
            gn.setdefault(nm, []).append((float(c[4]), float(c[5])))
gn_ok = 0
for p in places:
    if p["c"] == "m":
        ds = [hav(p["lat"], p["lon"], a, b) for a, b in gn.get(p["n"], [])]
        if not ds:
            notes.append("GeoNames neturi: " + p["n"])
        elif min(ds) > 3:
            problems.append("GeoNames skiriasi %.1f km: %s" % (min(ds), p["n"]))
        else:
            gn_ok += 1
notes.append("GeoNames patvirtino %d miestų koordinates (<3 km)" % gn_ok)

CATS = {"m": "miestai", "p": "pilys", "v": "vandenys", "g": "gamta", "i": "įdomybės"}
print("vietų:", len(places))
for c, cn in CATS.items():
    cnt = [sum(1 for p in places if p["c"] == c and p["d"] == d) for d in (1, 2, 3)]
    print("  %-9s lengvų %2d, vidutinių %2d, sunkių %2d, iš viso %3d" % (cn, *cnt, sum(cnt)))
    if min(cnt) < 10:
        problems.append("per mažai vietų: " + cn)
srcs = {}
for p in places:
    srcs[p["src"]] = srcs.get(p["src"], 0) + 1
print("koordinačių šaltiniai:", srcs)
if len(places) < 150:
    problems.append("mažiau nei 150 vietų")
for s in notes:
    print(" ·", s)
if problems:
    print("PROBLEMOS:")
    for s in problems:
        print("  !", s)
    sys.exit(1)

# ---------- išvestis ----------
MAIN = ["Nemunas", "Neris", "Šventoji", "Nevėžis", "Venta"]
data = {
    "o": [E0, N0, U], "box": [BW / U, BH / U],
    "land": [enc(p.exterior.coords) for p in polys(LT_SIMPLE)],
    "foreign": [enc(p.exterior.coords) for p in foreign_faces],
    "border": [enc(l.coords) for l in border_lines],
    "coast": [enc(l.coords) for l in coast_lines],
    "counties": [enc(l.coords) for l in county_lines],
    "ne": [enc(l.coords) for l in ne],
    "rivers": {nm: by[nm]["s"] for nm in MAIN},
    "shapes": shapes,
    "places": [[p["n"], p["c"], p["d"], p["k"], p["lat"], p["lon"], p["v"], p["f"], p["s"], p["r"]] for p in places],
}
out = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
npts = lambda k: sum(len(a) // 2 for a in data[k])
print("taškų: sausuma %d, užsienis %d, siena %d, pakrantė %d, apskritys %d, kaimynų sienos %d, vietų figūros %d; %d KB" % (
    npts("land"), npts("foreign"), npts("border"), npts("coast"), npts("counties"), npts("ne"),
    sum(len(a) // 2 for s in shapes for a in s["g"]), len(out.encode()) // 1024))

html = os.path.join(HERE, "kur-lietuvoje.html")
if os.path.exists(html):
    src = open(html, encoding="utf-8").read()
    new, k = re.subn(r"/\*DATA\*/.*?/\*END\*/", lambda m: "/*DATA*/" + out + "/*END*/", src, flags=re.S)
    assert k == 1, "kur-lietuvoje.html turi turėti vieną /*DATA*/…/*END*/ žymę"
    open(html, "w", encoding="utf-8").write(new)
    print("įrašyta į kur-lietuvoje.html")

if len(sys.argv) > 2:  # peržiūros SVG
    def d(arr, close):
        x = y = 0
        s = []
        for i in range(0, len(arr), 2):
            x += arr[i]; y += arr[i + 1]
            s.append("%s%d %d" % ("M" if i == 0 else "L", x, y))
        return "".join(s) + ("Z" if close else "")
    svg = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" width="1500"><rect width="100%%" height="100%%" fill="#bcd"/>' % tuple(data["box"])]
    svg.append('<path d="%s" fill="#ddd"/>' % "".join(d(a, 1) for a in data["foreign"]))
    svg.append('<path d="%s" fill="#f4efe0"/>' % "".join(d(a, 1) for a in data["land"]))
    for s in shapes:
        if s["t"] == "a":
            svg.append('<path d="%s" fill="#3a78" stroke="#274" stroke-width="10"/>' % "".join(d(a, 1) for a in s["g"]))
        else:
            svg.append('<path d="%s" fill="none" stroke="#27c" stroke-width="20"/>' % "".join(d(a, 0) for a in s["g"]))
    svg.append('<path d="%s" fill="none" stroke="#999" stroke-width="12" stroke-dasharray="60 40"/>' % "".join(d(a, 0) for a in data["counties"]))
    svg.append('<path d="%s" fill="none" stroke="#777" stroke-width="15"/>' % "".join(d(a, 0) for a in data["ne"]))
    svg.append('<path d="%s" fill="none" stroke="#a33" stroke-width="30"/>' % "".join(d(a, 0) for a in data["border"]))
    svg.append('<path d="%s" fill="none" stroke="#136" stroke-width="20"/>' % "".join(d(a, 0) for a in data["coast"]))
    for p in places:
        x, y = P(p["lon"], p["lat"])
        svg.append('<circle cx="%d" cy="%d" r="45" fill="#c22"/>' % (x / U, y / U))
    open(sys.argv[2], "w").write("\n".join(svg) + "</svg>")
