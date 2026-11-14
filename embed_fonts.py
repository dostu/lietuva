"""Įdeda Google Fonts šriftus (latin + latin-ext, woff2) tiesiai į kur-lietuvoje.html, kad žaidimas nesikreiptų į išorę.

Naudojimas: python -I embed_fonts.py <cache_dir>
"""
import base64, os, re, sys, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = sys.argv[1]
CSS = "https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@600;700&family=Barlow:wght@400;600&family=Literata:ital,wght@1,400..500&display=swap"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"}


def get(url):
    path = os.path.join(CACHE, re.sub(r"\W+", "_", url)[-120:])
    if not os.path.exists(path):
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
            open(path, "wb").write(r.read())
    return open(path, "rb").read()


out, total = [], 0
for subset, block in re.findall(r"/\* ([\w-]+) \*/\s*(@font-face \{.*?\})", get(CSS).decode(), flags=re.S):
    if subset not in ("latin", "latin-ext"):
        continue
    url = re.search(r"url\((https://[^)]+\.woff2)\)", block).group(1)
    data = get(url)
    total += len(data)
    out.append(re.sub(r"\s+", " ", block.replace(url, "data:font/woff2;base64," + base64.b64encode(data).decode())))
html = os.path.join(HERE, "kur-lietuvoje.html")
src = open(html, encoding="utf-8").read()
new, k = re.subn(r"/\*FONTS\*/.*?/\*END-FONTS\*/", lambda m: "/*FONTS*/" + "\n".join(out) + "/*END-FONTS*/", src, flags=re.S)
assert k == 1, "kur-lietuvoje.html turi turėti /*FONTS*/…/*END-FONTS*/ žymę"
open(html, "w", encoding="utf-8").write(new)
print(len(out), "šriftų failai,", total // 1024, "KB")
