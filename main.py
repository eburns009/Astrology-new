from flask import Flask, render_template, request, Response
import swisseph as swe
from datetime import datetime

app = Flask(__name__)

@app.get("/healthz")
def healthz():
    return "ok", 200

# ---------- Aspect set (angle°, default orb°, line color) ----------
ASPECTS = [
    {"name": "Conjunction",   "angle": 0.00,   "orb": 12.00, "color": "#2563eb"},
    {"name": "Semi-Sextile",  "angle": 30.00,  "orb": 10.00, "color": "#2563eb"},
    {"name": "Semi-Square",   "angle": 45.00,  "orb": 3.13,  "color": "#ef4444"},
    {"name": "Septile",       "angle": 51.26,  "orb": 3.13,  "color": "#8b5cf6"},
    {"name": "Sextile",       "angle": 60.00,  "orb": 5.21,  "color": "#2563eb"},
    {"name": "Quintile",      "angle": 72.00,  "orb": 6.38,  "color": "#22c55e"},
    {"name": "Square",        "angle": 90.00,  "orb": 7.00,  "color": "#ef4444"},
    {"name": "Bi-Septile",    "angle": 102.51, "orb": 5.50,  "color": "#8b5cf6"},
    {"name": "Trine",         "angle": 120.00, "orb": 10.30, "color": "#2563eb"},
    {"name": "Sesqui-Square", "angle": 135.00, "orb": 4.30,  "color": "#ef4444"},
    {"name": "Bi-Quintile",   "angle": 144.00, "orb": 4.30,  "color": "#22c55e"},
    {"name": "Tri-Septile",   "angle": 154.17, "orb": 5.46,  "color": "#8b5cf6"},
    {"name": "Opposition",    "angle": 180.00, "orb": 12.00, "color": "#ef4444"},
]

PLANETS = [
    (swe.SUN, "Sun"), (swe.MOON, "Moon"), (swe.MERCURY, "Mercury"),
    (swe.VENUS, "Venus"), (swe.MARS, "Mars"), (swe.JUPITER, "Jupiter"),
    (swe.SATURN, "Saturn"), (swe.URANUS, "Uranus"), (swe.NEPTUNE, "Neptune"),
    (swe.PLUTO, "Pluto"),
]

# Add lunar nodes (True Node; South Node opposite)
INCLUDE_NODES = True

SIGNS = ["Aries","Taurus","Gemini","Cancer","Leo","Virgo",
         "Libra","Scorpio","Sagittarius","Capricorn","Aquarius","Pisces"]

PLANET_GLYPHS = {
    "Sun":"☉","Moon":"☽","Mercury":"☿","Venus":"♀","Mars":"♂",
    "Jupiter":"♃","Saturn":"♄","Uranus":"♅","Neptune":"♆","Pluto":"♇",
    "North Node":"☊","South Node":"☋"
}
SIGN_GLYPHS = ["♈︎","♉︎","♊︎","♋︎","♌︎","♍︎","♎︎","♏︎","♐︎","♑︎","♒︎","♓︎"]

# keep last computed chart for the /chart.svg endpoint
LAST = {
    "names": None,     # list[str]
    "longs": None,     # list[float] — chosen zodiac (tropical or sidereal)
    "house_cusps": None,  # list[float] 12 cusps
    "asc": None, "mc": None,
    "title": "",
}

def norm(d): return d % 360.0
def sign_of(d): return SIGNS[int((d % 360.0)//30)]

def parse_local_time(date_str, hour, minute, ampm):
    h = int(hour)
    m = int(minute)
    ampm = ampm.upper()
    if ampm == "PM" and h != 12: h += 12
    if ampm == "AM" and h == 12: h = 0
    # Julian Day in UT — we treat input as UT to keep UI simple (you can add tz later)
    y,mn,dy = map(int, date_str.split("-"))
    jd = swe.julday(y, mn, dy, h + m/60.0)
    return jd, (y,mn,dy,h,m)

def compute_positions(jd, zodiac, lat, lon, house_mode):
    """
    zodiac: 'tropical' or 'sidereal' (Fagan/Allen)
    house_mode:
      'EQUAL_ASC_CUSP'  -> Equal with Asc on cusp 1 (Swiss 'E')
      'EQUAL_ASC_MID'   -> Equal with Asc in the middle of 1st
      'PLACIDUS'        -> Swiss 'P'
    """
    # Tropical longitudes
    trop = {}
    for code, name in PLANETS:
        vals, _ = swe.calc_ut(jd, code)
        trop[name] = norm(vals[0])

    # Nodes (true)
    if INCLUDE_NODES:
        nn_vals, _ = swe.calc_ut(jd, swe.TRUE_NODE)
        nn = norm(nn_vals[0])
        sn = norm(nn + 180.0)
        trop["North Node"] = nn
        trop["South Node"] = sn

    # Sidereal ayanamsa (Fagan/Bradley)
    swe.set_sid_mode(swe.SIDM_FAGAN_BRADLEY)
    ayan = swe.get_ayanamsa_ut(jd)

    rows = []
    for name, lon_t in trop.items():
        lon_s = norm(lon_t - ayan)
        rows.append({
            "name": name,
            "trop": lon_t, "trop_sign": sign_of(lon_t),
            "sid": lon_s,  "sid_sign": sign_of(lon_s),
        })

    # Houses
    if house_mode == "PLACIDUS":
        cusps, ascmc = swe.houses(jd, lat, lon, b'P')
        cusps = [norm(c) for c in cusps]
        asc, mc = norm(ascmc[0]), norm(ascmc[1])
    else:
        cusps_E, ascmc = swe.houses(jd, lat, lon, b'E')  # equal with Asc on cusp (Swiss default)
        asc, mc = norm(ascmc[0]), norm(ascmc[1])
        if house_mode == "EQUAL_ASC_CUSP":
            cusps = [norm(c) for c in cusps_E]
        else:
            # Equal with Asc at middle => cusps every 30°, centered so that Asc is 15° into house 1
            base = norm(asc - 15.0)
            cusps = [norm(base + i*30.0) for i in range(12)]

    # Choose which zodiac to drive downstream (positions & SVG)
    if zodiac == "sidereal":
        chosen_longs = [r["sid"] for r in rows]
        title = "Sidereal (Fagan/Allen)"
    else:
        chosen_longs = [r["trop"] for r in rows]
        title = "Tropical"

    names = [r["name"] for r in rows]
    return rows, names, chosen_longs, cusps, asc, mc, ayan, title

def min_sep(a, b):
    d = abs((a - b) % 360.0)
    return d if d <= 180 else 360 - d

def find_aspects(longs):
    """Return list of (i,j, angle_hit, color) for planet pairs within orb."""
    hits = []
    n = len(longs)
    for i in range(n):
        for j in range(i+1, n):
            sep = min_sep(longs[i], longs[j])
            for asp in ASPECTS:
                if abs(sep - asp["angle"]) <= asp["orb"]:
                    hits.append((i, j, asp["angle"], asp["color"]))
                    break
    return hits

@app.route("/", methods=["GET", "POST"])
def index():
    results = houses = None
    ayanamsa = None
    form = {"date":"1962-07-02","hour":"11","minute":"33","ampm":"PM",
            "lat":"37.90","lon":"-85.95","zodiac":"tropical","house_system":"EQUAL_ASC_CUSP"}
    if request.method == "POST":
        form["date"]   = request.form.get("date", form["date"])
        form["hour"]   = request.form.get("hour", form["hour"])
        form["minute"] = request.form.get("minute", form["minute"])
        form["ampm"]   = request.form.get("ampm", form["ampm"])
        form["lat"]    = request.form.get("lat", form["lat"])
        form["lon"]    = request.form.get("lon", form["lon"])
        form["zodiac"] = request.form.get("zodiac", form["zodiac"])
        form["house_system"] = request.form.get("house_system", form["house_system"])

        try:
            jd, _ = parse_local_time(form["date"], form["hour"], form["minute"], form["ampm"])
            lat = float(form["lat"]); lon = float(form["lon"])
            rows, names, chosen_longs, cusps, asc, mc, ayan, title = compute_positions(
                jd, form["zodiac"], lat, lon, form["house_system"]
            )
            # Save for chart
            LAST["names"] = names
            LAST["longs"] = chosen_longs
            LAST["house_cusps"] = cusps
            LAST["asc"] = asc; LAST["mc"] = mc
            LAST["title"] = title

            results = rows
            houses  = {"cusps": cusps, "asc": asc, "mc": mc}
            ayanamsa = ayan if form["zodiac"] == "sidereal" else None
        except Exception as e:
            return render_template("index.html", page_error=str(e), form=form, aspects=ASPECTS)

    return render_template("index.html", results=results, houses=houses, ayanamsa=ayanamsa,
                           aspects=ASPECTS, form=form)

@app.get("/chart.svg")
def chart_svg():
    """
    Render an SVG wheel:
      - Outer zodiac ring with big sign glyphs
      - House cusps as spokes
      - Planets/nodes as big glyphs
      - Aspect lines colored per table
    """
    import math
    names = LAST.get("names") or []
    longs = LAST.get("longs") or []
    cusps = LAST.get("house_cusps") or []
    asc = LAST.get("asc"); mc = LAST.get("mc")
    title = LAST.get("title","")

    size = 720
    cx = cy = size//2
    R_outer = size//2 - 12
    R_signs = R_outer - 26
    R_planets = R_outer - 80
    R_aspects = R_planets  # draw lines at planet radius

    def pol(r, deg):
        # 0° Aries at left (9 o'clock); increase clockwise
        a = math.radians(180 - deg)
        return cx + r*math.cos(a), cy - r*math.sin(a)

    svg = []
    svg.append(f"<svg xmlns='http://www.w3.org/2000/svg' width='{size}' height='{size}' viewBox='0 0 {size} {size}'>")
    svg.append("<defs><style>@font-face{font-family:system-ui;src:local('Arial');}</style></defs>")
    svg.append(f"<rect width='100%' height='100%' fill='#cce7ff'/>")
    svg.append(f"<text x='{cx}' y='28' text-anchor='middle' font-size='20' fill='#003366'>{title} Chart</text>")
    svg.append(f"<circle cx='{cx}' cy='{cy}' r='{R_outer}' fill='#fff' stroke='#003366' stroke-width='2'/>")

    # 12 sign slices + glyphs
    for i in range(12):
        deg0 = i*30.0
        x,y = pol(R_outer, deg0)
        svg.append(f"<line x1='{cx}' y1='{cy}' x2='{x:.1f}' y2='{y:.1f}' stroke='#99b3ff'/>")
        sx,sy = pol(R_signs, deg0 + 15.0)
        glyph = SIGN_GLYPHS[i]
        svg.append(f"<text x='{sx:.1f}' y='{sy:.1f}' text-anchor='middle' dominant-baseline='middle' "
                   f"font-size='28' fill='#003366'>{glyph}</text>")

    # House cusps
    if cusps:
        for i, c in enumerate(cusps, start=1):
            x,y = pol(R_outer, c)
            svg.append(f"<line x1='{cx}' y1='{cy}' x2='{x:.1f}' y2='{y:.1f}' stroke='#003366' "
                       f"stroke-width='{2 if i in (1,4,7,10) else 1}'/>")
            # house number label slightly inside
            hx,hy = pol(R_signs-18, c+2)
            svg.append(f"<text x='{hx:.1f}' y='{hy:.1f}' font-size='14' fill='#003366' "
                       f"text-anchor='middle' dominant-baseline='middle'>{i}</text>")

    # Planet glyph positions
    pts = []
    for nm, lo in zip(names, longs):
        x,y = pol(R_planets, lo)
        glyph = PLANET_GLYPHS.get(nm, nm[:1])
        svg.append(f"<circle cx='{x:.1f}' cy='{y:.1f}' r='12' fill='#ffffff' stroke='#003366'/>")
        svg.append(f"<text x='{x:.1f}' y='{y+4:.1f}' text-anchor='middle' dominant-baseline='middle' "
                   f"font-size='22' fill='#003366'>{glyph}</text>")
        pts.append((x,y))

    # Aspect lines
    if longs:
        hits = find_aspects(longs)
        for i,j,ang,color in hits:
            x1,y1 = pts[i]; x2,y2 = pts[j]
            svg.append(f"<line x1='{x1:.1f}' y1='{y1:.1f}' x2='{x2:.1f}' y2='{y2:.1f}' "
                       f"stroke='{color}' stroke-width='2' opacity='0.9'/>")

    svg.append("</svg>")
    return Response("\n".join(svg), mimetype="image/svg+xml")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
