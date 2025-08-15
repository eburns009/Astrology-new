from flask import Flask, request, render_template_string, url_for
import datetime
from zoneinfo import ZoneInfo
import requests
import swisseph as swe

app = Flask(__name__)

# ---------- CONFIG ----------
GEONAMES_USERNAME = "newastologyemerging"
DEFAULT_FB_EXTRA_OFFSET_DEG = 0.2103  # set 0.0 for pure Swiss F/B

PLANETS = [
    ("Sun", swe.SUN), ("Moon", swe.MOON), ("Mercury", swe.MERCURY),
    ("Venus", swe.VENUS), ("Mars", swe.MARS), ("Jupiter", swe.JUPITER),
    ("Saturn", swe.SATURN), ("Uranus", swe.URANUS), ("Neptune", swe.NEPTUNE),
    ("Pluto", swe.PLUTO),
]

HTML = """
<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Planet Positions (Tropical & Sidereal FB + GeoNames)</title>
<style>
  body{font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif;max-width:920px;margin:32px auto;padding:0 16px}
  h1{margin:0 0 8px}
  .row{display:flex;gap:12px;flex-wrap:wrap;align-items:center;margin:.35rem 0}
  label{min-width:140px}
  input{padding:.4rem .55rem}
  button{padding:.5rem .8rem;cursor:pointer}
  table{width:100%;border-collapse:collapse;margin-top:12px}
  th,td{border:1px solid #ddd;padding:.5rem;text-align:left}
  .card{border:1px solid #ddd;border-radius:8px;padding:10px;margin:10px 0}
  .muted{color:#666}
  .success{background:#f5fff6;border-color:#cfe9d1}
  ul{margin:.5rem 0 .25rem 1.25rem}
  form.inline{display:inline}
</style>
</head>
<body>
  <h1>Planet Positions</h1>
  <p class="muted">Search & pick a city (GeoNames), enter local date/time; app converts to UT and computes positions. Toggle Sidereal (Fagan/Bradley). Offset lets you match a specific SVP flavor.</p>

  <!-- City search -->
  <form method="GET" action="/" class="row" style="align-items:flex-end">
    <div>
      <label for="q">City search</label>
      <input id="q" name="q" placeholder="e.g., Fort Knox, Boulder, London" value="{{ q or '' }}">
    </div>
    <div>
      <button type="submit" name="action" value="search">Search</button>
    </div>
  </form>

  {% if city_results %}
    <div class="card">
      <strong>Results:</strong>
      <ul>
        {% for c in city_results %}
          <li>
            {{ c["name"] }}{% if c["adminName1"] %}, {{ c["adminName1"] }}{% endif %}, {{ c["countryName"] }}
            — lat {{ c["lat"] }}, lon {{ c["lng"] }}
            <form method="POST" action="{{ url_for('select_city') }}" class="inline">
              <input type="hidden" name="name" value="{{ c['name'] }}">
              <input type="hidden" name="adminName1" value="{{ c.get('adminName1','') }}">
              <input type="hidden" name="countryName" value="{{ c.get('countryName','') }}">
              <input type="hidden" name="lat" value="{{ c['lat'] }}">
              <input type="hidden" name="lng" value="{{ c['lng'] }}">
              <button type="submit">Use this</button>
            </form>
          </li>
        {% endfor %}
      </ul>
    </div>
  {% endif %}

  {% if selected_city %}
    <div class="card success">
      <strong>Selected city:</strong> {{ selected_city["label"] }}<br>
      <span class="muted">Lat {{ selected_city["lat"] }}, Lon {{ selected_city["lng"] }} • Timezone: {{ selected_city["tzid"] }}</span>
    </div>
  {% endif %}

  <!-- Compute form -->
  <form method="POST" action="/" class="row" style="align-items:flex-end">
    <div>
      <label>Date (YYYY-MM-DD)</label>
      <input name="date" value="{{ date or '1962-07-02' }}">
    </div>
    <div>
      <label>Time (HH:MM)</label>
      <input name="time" value="{{ time or '23:33' }}">
    </div>
    <div>
      <label>Timezone (IANA)</label>
      <input name="tzid" value="{{ (selected_city['tzid'] if selected_city else tzid) or 'America/New_York' }}">
    </div>
    <div>
      <label><input type="checkbox" name="sidereal" value="fb" {% if sidereal %}checked{% endif %}> Sidereal (Fagan/Bradley)</label>
    </div>
    <div>
      <label>Extra offset (°)</label>
      <input name="fb_offset" value="{{ fb_offset if fb_offset is not none else '0.2103' }}">
    </div>

    <!-- hidden lat/lon if chosen -->
    <input type="hidden" name="lat" value="{{ selected_city['lat'] if selected_city else '' }}">
    <input type="hidden" name="lng" value="{{ selected_city['lng'] if selected_city else '' }}">
    <button type="submit">Compute</button>
  </form>

  {% if results %}
    <p class="muted">Local {{ local_str }} ({{ tzid }}) → UTC {{ utc_str }} • JD {{ jd }}
    {% if sidereal %} • F/B ayanāṃśa used (incl. offset): {{ ayan_used }}°{% endif %}</p>

    <table>
      <tr>
        <th>Body</th><th>Tropical (°)</th>
        {% if sidereal %}<th>Sidereal F/B (°)</th><th>Sidereal Sign</th>{% endif %}
      </tr>
      {% for r in results %}
        <tr>
          <td>{{ r.name }}</td>
          <td>{{ r.trop }}</td>
          {% if sidereal %}<td>{{ r.sid }}</td><td>{{ r.sign }}</td>{% endif %}
        </tr>
      {% endfor %}
    </table>
  {% endif %}
</body>
</html>
"""

def geonames_search(q: str):
    """Search cities via GeoNames."""
    url = "http://api.geonames.org/searchJSON"
    params = {
        "q": q, "maxRows": 10, "username": GEONAMES_USERNAME,
        "featureClass": "P", "orderby": "relevance"
    }
    r = requests.get(url, params=params, timeout=12)
    r.raise_for_status()
    data = r.json()
    out = []
    for g in data.get("geonames", []):
        out.append({
            "name": g.get("name", ""),
            "countryName": g.get("countryName", ""),
            "adminName1": g.get("adminName1", ""),
            "lat": str(g.get("lat")),
            "lng": str(g.get("lng")),
        })
    return out

def geonames_timezone(lat: float, lng: float) -> str:
    """Get IANA timezone for coordinates via GeoNames timezone API."""
    url = "http://api.geonames.org/timezoneJSON"
    params = {"lat": lat, "lng": lng, "username": GEONAMES_USERNAME}
    r = requests.get(url, params=params, timeout=12)
    r.raise_for_status()
    tzid = r.json().get("timezoneId")
    if not tzid:
        raise ValueError("No timezoneId returned")
    return tzid

def fmt_zodiac(deg: float) -> str:
    signs = ["Aries","Taurus","Gemini","Cancer","Leo","Virgo",
             "Libra","Scorpio","Sagittarius","Capricorn","Aquarius","Pisces"]
    lon = deg % 360.0
    si = int(lon // 30)
    x = lon - si*30
    d = int(x)
    m_full = (x - d) * 60
    m = int(m_full)
    s = int(round((m_full - m) * 60))
    if s == 60:
        s = 0; m += 1
    if m == 60:
        m = 0; d += 1
    return f"{d:02d}°{m:02d}'{s:02d}\" {signs[si]}"

@app.route("/", methods=["GET","POST"])
def index():
    q = request.args.get("q", "").strip() if request.method == "GET" else ""
    action = request.args.get("action") if request.method == "GET" else None
    city_results = None
    selected_city = None
    results = None
    results_meta = {}
    date_val = time_val = tzid = None
    sidereal = False
    fb_offset_val = None

    # Handle city search
    if request.method == "GET" and action == "search" and q:
        try:
            city_results = geonames_search(q)
        except Exception as e:
            city_results = [{"name":"Error","countryName":str(e),"adminName1":"","lat":"","lng":""}]

    if request.method == "POST":
        date_val = (request.form.get("date") or "").strip()
        time_val = (request.form.get("time") or "").strip()
        tzid = (request.form.get("tzid") or "UTC").strip()
        sidereal = (request.form.get("sidereal") == "fb")

        # offset
        try:
            fb_offset_val = float((request.form.get("fb_offset") or "").strip())
        except Exception:
            fb_offset_val = DEFAULT_FB_EXTRA_OFFSET_DEG

        # if hidden lat/lon present, try timezone lookup when tz missing/placeholder
        lat = request.form.get("lat")
        lng = request.form.get("lng")
        if (not tzid or tzid.upper() == "AUTO") and lat and lng:
            try:
                tzid = geonames_timezone(float(lat), float(lng))
            except Exception:
                tzid = "UTC"

        # Local -> UTC
        local_dt = datetime.datetime.strptime(f"{date_val} {time_val}", "%Y-%m-%d %H:%M")
        try:
            tz = ZoneInfo(tzid)
        except Exception:
            tz = ZoneInfo("UTC"); tzid = "UTC"
        local_dt = local_dt.replace(tzinfo=tz)
        utc_dt = local_dt.astimezone(datetime.timezone.utc)

        # JD (UT)
        hour_dec = utc_dt.hour + utc_dt.minute/60 + utc_dt.second/3600
        jd = swe.julday(utc_dt.year, utc_dt.month, utc_dt.day, hour_dec)

        # Ayanamsa
        if sidereal:
            swe.set_sid_mode(swe.SIDM_FAGAN_BRADLEY)
            ayan = swe.get_ayanamsa_ut(jd) + fb_offset_val
            results_meta["ayan_used"] = f"{ayan:.6f}"
        else:
            ayan = 0.0

        rows = []
        for name, code in PLANETS:
            lon, latp, dist = swe.calc_ut(jd, code)[:3]
            if sidereal:
                sid = (lon - ayan) % 360.0
                rows.append(type("R", (), {
                    "name": name, "trop": f"{lon:.6f}", "sid": f"{sid:.6f}", "sign": fmt_zodiac(sid)
                }))
            else:
                rows.append(type("R", (), {"name": name, "trop": f"{lon:.6f}"}))

        results = rows
        results_meta.update({
            "tzid": tzid,
            "local_str": local_dt.strftime("%Y-%m-%d %H:%M"),
            "utc_str": utc_dt.strftime("%Y-%m-%d %H:%M"),
            "jd": f"{jd:.5f}",
        })

        return render_template_string(
            HTML,
            q=None, city_results=None, selected_city=selected_city,
            results=results, date=date_val, time=time_val, tzid=tzid,
            sidereal=sidereal, fb_offset=fb_offset_val,
            local_str=results_meta["local_str"], utc_str=results_meta["utc_str"],
            jd=results_meta["jd"], ayan_used=results_meta.get("ayan_used")
        )

    # GET default (prefill with your birth data)
    return render_template_string(
        HTML,
        q=q, city_results=city_results, selected_city=selected_city,
        results=None, date="1962-07-02", time="23:33", tzid="America/New_York",
        sidereal=True, fb_offset=DEFAULT_FB_EXTRA_OFFSET_DEG
    )

@app.route("/select_city", methods=["POST"])
def select_city():
    name = request.form.get("name","")
    admin = request.form.get("adminName1","")
    country = request.form.get("countryName","")
    lat = float(request.form.get("lat"))
    lng = float(request.form.get("lng"))
    try:
        tzid = geonames_timezone(lat, lng)
    except Exception:
        tzid = "UTC"
    selected = {
        "label": f"{name}{', ' + admin if admin else ''}, {country}",
        "lat": lat, "lng": lng, "tzid": tzid
    }
    # Re-show main page with selection stored
    return render_template_string(
        HTML,
        q=None, city_results=None, selected_city=selected,
        results=None, date="1962-07-02", time="23:33",
        tzid=tzid, sidereal=True, fb_offset=DEFAULT_FB_EXTRA_OFFSET_DEG
    )

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
