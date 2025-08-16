from flask import Flask, render_template, request, Response
import swisseph as swe
import requests, os
from datetime import datetime

app = Flask(__name__)

@app.get("/healthz")
def healthz():
    return "ok", 200

GEONAMES_USERNAME = os.getenv("GEONAMES_USERNAME", "newastologyemerging")
GEONAMES_BASE = "http://api.geonames.org"

def geonames_search(q, max_rows=8):
    r = requests.get(f"{GEONAMES_BASE}/searchJSON",
                     params={"q": q, "maxRows": max_rows, "username": GEONAMES_USERNAME, "featureClass": "P", "orderby": "relevance"},
                     timeout=10)
    data = r.json()
    if "status" in data:
        raise RuntimeError(data["status"].get("message", "GeoNames error"))
    out = []
    for g in data.get("geonames", []):
        out.append({"name": g.get("name",""), "admin": g.get("adminName1",""),
                    "country": g.get("countryName",""), "lat": g.get("lat",""),
                    "lng": g.get("lng","")})
    return out

SIGNS = ["Aries","Taurus","Gemini","Cancer","Leo","Virgo",
         "Libra","Scorpio","Sagittarius","Capricorn","Aquarius","Pisces"]

PLANETS = [
    (swe.SUN, "Sun"), (swe.MOON, "Moon"), (swe.MERCURY, "Mercury"),
    (swe.VENUS, "Venus"), (swe.MARS, "Mars"), (swe.JUPITER, "Jupiter"),
    (swe.SATURN, "Saturn"), (swe.URANUS, "Uranus"), (swe.NEPTUNE, "Neptune"),
    (swe.PLUTO, "Pluto")
]

def norm(d): return d % 360.0
def sign_of(d): return SIGNS[int((d%360)//30)]

def parse_local_time(date_str, hour, minute, ampm):
    h = int(hour); m = int(minute); ap = ampm.upper()
    if ap == "PM" and h != 12: h += 12
    if ap == "AM" and h == 12: h = 0
    y,mo,dy = map(int, date_str.split("-"))
    jd = swe.julday(y, mo, dy, h + m/60.0)  # treat as UT for simplicity
    return jd

def compute_rows(jd, zodiac):
    swe.set_sid_mode(swe.SIDM_FAGAN_BRADLEY)
    ayan = swe.get_ayanamsa_ut(jd)
    rows = []
    for code, name in PLANETS:
        vals, _ = swe.calc_ut(jd, code)
        lon_t = norm(vals[0])
        lon_s = norm(lon_t - ayan)
        rows.append({
            "name": name,
            "trop": lon_t, "trop_sign": sign_of(lon_t),
            "sid": lon_s,  "sid_sign": sign_of(lon_s)
        })
    return rows, (ayan if zodiac == "sidereal" else None)

@app.route("/", methods=["GET", "POST"])
def index():
    form = {"date":"1962-07-02","hour":"11","minute":"33","ampm":"PM",
            "lat":"37.90","lon":"-85.95","zodiac":"tropical", "city_q":""}
    results = None
    city_results = None
    page_error = None
    ayanamsa = None

    # City search
    q = (request.args.get("city") or "").strip()
    if q:
        try:
            city_results = geonames_search(q)
        except Exception as e:
            page_error = f"GeoNames: {e}"

    if request.method == "POST":
        for k in ["date","hour","minute","ampm","lat","lon","zodiac"]:
            form[k] = request.form.get(k, form[k])
        try:
            jd = parse_local_time(form["date"], form["hour"], form["minute"], form["ampm"])
            results, ayanamsa = compute_rows(jd, form["zodiac"])
        except Exception as e:
            page_error = str(e)

    return render_template("index.html",
                           form=form, results=results, ayanamsa=ayanamsa,
                           city_results=city_results, page_error=page_error)

@app.get("/chart.svg")
def chart_svg():
    # simple placeholder chart (renders even if no results yet)
    return Response(
        "<svg xmlns='http://www.w3.org/2000/svg' width='300' height='300'>"
        "<rect width='100%' height='100%' fill='#cce7ff'/>"
        "<circle cx='150' cy='150' r='120' fill='white' stroke='#003366' stroke-width='2'/>"
        "</svg>", mimetype="image/svg+xml"
    )

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
