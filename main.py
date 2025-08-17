from flask import Flask, render_template, request, Response
import os, requests
import swisseph as swe

app = Flask(__name__)

# ---------- Health check for Render ----------
@app.get("/healthz")
def healthz():
    return "ok", 200

# ---------- GeoNames ----------
GEONAMES_USERNAME = os.getenv("GEONAMES_USERNAME", "newastologyemerging")
GEONAMES_BASE = "http://api.geonames.org"

def geonames_search(q, max_rows=8):
    r = requests.get(f"{GEONAMES_BASE}/searchJSON",
                     params={"q": q, "maxRows": max_rows, "username": GEONAMES_USERNAME,
                             "featureClass": "P", "orderby": "relevance"},
                     timeout=10)
    data = r.json()
    if "status" in data:
        msg = data["status"].get("message", "GeoNames error")
        code = data["status"].get("value", "")
        raise RuntimeError(f"{msg} (status {code})")
    out = []
    for g in data.get("geonames", []):
        out.append({
            "name": g.get("name",""),
            "admin": g.get("adminName1",""),
            "country": g.get("countryName",""),
            "lat": g.get("lat",""),
            "lng": g.get("lng",""),
        })
    return out

# ---------- Astrology constants ----------
SIGNS = ["Aries","Taurus","Gemini","Cancer","Leo","Virgo",
         "Libra","Scorpio","Sagittarius","Capricorn","Aquarius","Pisces"]

PLANETS = [
    (swe.SUN, "Sun"), (swe.MOON, "Moon"), (swe.MERCURY, "Mercury"),
    (swe.VENUS, "Venus"), (swe.MARS, "Mars"), (swe.JUPITER, "Jupiter"),
    (swe.SATURN, "Saturn"), (swe.URANUS, "Uranus"), (swe.NEPTUNE, "Neptune"),
    (swe.PLUTO, "Pluto"),
]

PLANET_GLYPHS = {
    "Sun":"☉","Moon":"☽","Mercury":"☿","Venus":"♀","Mars":"♂",
    "Jupiter":"♃","Saturn":"♄","Uranus":"♅","Neptune":"♆","Pluto":"♇",
    "North Node":"☊","South Node":"☋"
}
SIGN_GLYPHS = ["♈︎","♉︎","♊︎","♋︎","♌︎","♍︎","♎︎","♏︎","♐︎","♑︎","♒︎","♓︎"]

ASPECTS = [
    {"name":"Conjunction","angle":0.00,"orb":12.00,"color":"#2563eb"},
    {"name":"Semi-Sextile","angle":30.00,"orb":10.00,"color":"#2563eb"},
    {"name":"Semi-Square","angle":45.00,"orb":3.13,"color":"#ef4444"},
    {"name":"Septile","angle":51.26,"orb":3.13,"color":"#8b5cf6"},
    {"name":"Sextile","angle":60.00,"orb":5.21,"color":"#2563eb"},
    {"name":"Quintile","angle":72.00,"orb":6.38,"color":"#22c55e"},
    {"name":"Square","angle":90.00,"orb":7.00,"color":"#ef4444"},
    {"name":"Bi-Septile","angle":102.51,"orb":5.50,"color":"#8b5cf6"},
    {"name":"Trine","angle":120.00,"orb":10.30,"color":"#2563eb"},
    {"name":"Sesqui-Square","angle":135.00,"orb":4.30,"color":"#ef4444"},
    {"name":"Bi-Quintile","angle":144.00,"orb":4.30,"color":"#22c55e"},
    {"name":"Tri-Septile","angle":154.17,"orb":5.46,"color":"#8b5cf6"},
    {"name":"Opposition","angle":180.00,"orb":12.00,"color":"#ef4444"},
]

# Scratch for SVG chart
LAST = {"names":None,"longs":None,"cusps":None,"asc":None,"mc":None,"title":""}

# ---------- Helpers ----------
def norm(d): return d % 360.0
def sign_of(d): return SIGNS[int((d%360)//30)]

def parse_time(date_str, hour, minute, ampm):
    h = int(hour); m = int(minute); ap = (ampm or "").upper()
    if ap == "PM" and h != 12: h += 12
    if ap == "AM" and h == 12: h = 0
    y,mo,dy = map(int, date_str.split("-"))
    return swe.julday(y, mo, dy, h + m/60.0)  # treat entered time as UT (simple)

def compute_all(jd, fb_extra_deg, lat, lon, house_mode, node_type):
    """
    Returns rows with Tropical and Sidereal(F/B + extra) side-by-side,
    plus houses (Equal/Placidus).
    """
    # tropical
    trop = {}
    for code, name in PLANETS:
        vals, _ = swe.calc_ut(jd, code)
        trop[name] = norm(vals[0])

    # nodes
    node_flag = swe.TRUE_NODE if node_type == "true" else swe.MEAN_NODE
    nvals, _ = swe.calc_ut(jd, node_flag)
    nn = norm(nvals[0])
    trop["North Node"] = nn
    trop["South Node"] = norm(nn + 180.0)

    # sidereal Fagan/Bradley (+ optional extra offset)
    swe.set_sid_mode(swe.SIDM_FAGAN_BRADLEY)
    ayan = swe.get_ayanamsa_ut(jd) + float(fb_extra_deg or 0.0)

    rows = []
    for name, tlon in trop.items():
        slon = norm(tlon - ayan)
        rows.append({
            "name": name,
            "trop": tlon, "trop_sign": sign_of(tlon),
            "sid": slon,  "sid_sign": sign_of(slon),
        })

    # houses
    if house_mode == "PLACIDUS":
        cusps, ascmc = swe.houses(jd, lat, lon, b'P')
        cusps = [norm(c) for c in cusps]
        asc, mc = norm(ascmc[0]), norm(ascmc[1])
    elif house_mode == "EQUAL_ASC_MID":
        cuspsE, ascmc = swe.houses(jd, lat, lon, b'E')
        asc, mc = norm(ascmc[0]), norm(ascmc[1])
        base = norm(asc - 15.0)
        cusps = [norm(base + i*30.0) for i in range(12)]
    else:  # EQUAL_ASC_CUSP
        cusps, ascmc = swe.houses(jd, lat, lon, b'E')
        cusps = [norm(c) for c in cusps]
        asc, mc = norm(ascmc[0]), norm(ascmc[1])

    names = [r["name"] for r in rows]
    # Use sidereal as the chart ring by default (can be changed)
    ring = [r["sid"] for r in rows]
    LAST.update({"names":names,"longs":ring,"cusps":cusps,"asc":asc,"mc":mc,"title":"Sidereal (F/A)"})
    return rows, cusps, asc, mc, ayan

def aspect_hits(longs):
    hits = []
    n = len(longs)
    for i in range(n):
        for j in range(i+1, n):
            sep = abs((longs[i] - longs[j]) % 360.0)
            if sep > 180: sep = 360 - sep
            for a in ASPECTS:
                if abs(sep - a["angle"]) <= a["orb"]:
                    hits.append((i,j,a["color"]))
                    break
    return hits

# ---------- Routes ----------
@app.route("/", methods=["GET","POST"])
def index():
    form = {
        "date":"1962-07-02","hour":"11","minute":"33","ampm":"PM",
        "lat":"37.90","lon":"-85.95",
        "house_system":"EQUAL_ASC_CUSP",
        "fb_offset":"0.0000",
        "node_type":"true"  # true | mean
    }
    page_error = None
    city_results = None
    results = None
    houses = None
    ayanamsa = None

    # GeoNames search via GET
    q = (request.args.get("city") or "").strip()
    if q:
        try:
            city_results = geonames_search(q)
        except Exception as e:
            page_error = f"GeoNames: {e}"

    if request.method == "POST":
        # City selection prefills lat/lon
        if request.form.get("select_city") == "1":
            form["lat"] = request.form.get("lat", form["lat"])
            form["lon"] = request.form.get("lng", form["lon"])
        else:
            for k in ["date","hour","minute","ampm","lat","lon","house_system","fb_offset","node_type"]:
                form[k] = request.form.get(k, form[k])
            try:
                jd = parse_time(form["date"], form["hour"], form["minute"], form["ampm"])
                rows, cusps, asc, mc, ayan = compute_all(
                    jd, form["fb_offset"], float(form["lat"]), float(form["lon"]),
                    form["house_system"], form["node_type"]
                )
                results = rows
                houses = {"cusps":cusps, "asc":asc, "mc":mc}
                ayanamsa = ayan
            except Exception as e:
                page_error = str(e)

    return render_template("index.html",
        form=form, results=results, houses=houses, ayanamsa=ayanamsa,
        aspects=ASPECTS, city_results=city_results, page_error=page_error)

@app.get("/chart.svg")
def chart_svg():
    import math
    names = LAST.get("names") or []
    longs = LAST.get("longs") or []
    cusps = LAST.get("cusps") or []
    title = LAST.get("title","")

    size = 720
    cx = cy = size//2
    R_outer = size//2 - 12
    R_signs = R_outer - 26
    R_planets = R_outer - 80

    def pol(r, deg):
        a = math.radians(180 - deg)  # 0 Aries left; clockwise increases
        return cx + r*math.cos(a), cy - r*math.sin(a)

    svg = []
    svg.append(f"<svg xmlns='http://www.w3.org/2000/svg' width='{size}' height='{size}' viewBox='0 0 {size} {size}'>")
    svg.append(f"<rect width='100%' height='100%' fill='#cce7ff'/>")
    svg.append(f"<text x='{cx}' y='28' text-anchor='middle' font-size='20' fill='#003366'>{title} Chart</text>")
    svg.append(f"<circle cx='{cx}' cy='{cy}' r='{R_outer}' fill='#fff' stroke='#003366' stroke-width='2'/>")

    # zodiac ring + glyphs
    for i in range(12):
        d0 = i*30.0
        x,y = pol(R_outer, d0)
        svg.append(f"<line x1='{cx}' y1='{cy}' x2='{x:.1f}' y2='{y:.1f}' stroke='#99b3ff'/>")
        sx,sy = pol(R_signs, d0+15.0)
        svg.append(f"<text x='{sx:.1f}' y='{sy:.1f}' text-anchor='middle' dominant-baseline='middle' "
                   f"font-size='28' fill='#003366'>{SIGN_GLYPHS[i]}</text>")

    # houses
    for i, c in enumerate(cusps, start=1):
        x,y = pol(R_outer, c)
        svg.append(f"<line x1='{cx}' y1='{cy}' x2='{x:.1f}' y2='{y:.1f}' "
                   f"stroke='{('#003366' if i in (1,4,7,10) else '#335b99')}' stroke-width='{2 if i in (1,4,7,10) else 1}'/>")
        hx,hy = pol(R_signs-18, c+2)
        svg.append(f"<text x='{hx:.1f}' y='{hy:.1f}' font-size='14' fill='#003366' "
                   f"text-anchor='middle' dominant-baseline='middle'>{i}</text>")

    # planets (sidereal ring saved in LAST)
    pts = []
    for nm, lo in zip(names, longs):
        x,y = pol(R_planets, lo)
        svg.append(f"<circle cx='{x:.1f}' cy='{y:.1f}' r='12' fill='#fff' stroke='#003366'/>")
        svg.append(f"<text x='{x:.1f}' y='{y+4:.1f}' text-anchor='middle' dominant-baseline='middle' "
                   f"font-size='22' fill='#003366'>{PLANET_GLYPHS.get(nm, nm[:1])}</text>")
        pts.append((x,y))

    # aspect lines
    if longs:
        for i,j,color in aspect_hits(longs):
            x1,y1 = pts[i]; x2,y2 = pts[j]
            svg.append(f"<line x1='{x1:.1f}' y1='{y1:.1f}' x2='{x2:.1f}' y2='{y2:.1f}' "
                       f"stroke='{color}' stroke-width='2' opacity='0.9'/>")

    svg.append("</svg>")
    return Response("\n".join(svg), mimetype="image/svg+xml")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
