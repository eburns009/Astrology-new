from flask import Flask, request, render_template_string, url_for
import os
import datetime
from zoneinfo import ZoneInfo
import requests
import swisseph as swe

app = Flask(__name__)

# ------------------ CONFIG ------------------
# Read GeoNames username from env var when available; fallback to your default
GEONAMES_USERNAME = os.getenv("GEONAMES_USERNAME", "newastologyemerging")
# Free tier requires HTTP, not HTTPS
GEONAMES_BASE = "http://api.geonames.org"
# Set to 0.0 for pure Swiss Fagan/Bradley; keep small offset if you must match an external SVP flavor
DEFAULT_FB_EXTRA_OFFSET_DEG = 0.2103

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
  .err{color:#b00020}
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
            <span class="{% if not c.get('_ok') %}err{% endif %}">
              {{ c["name"] }}{% if c.get("adminName1") %}, {{ c["adminName1"] }}{% endif %}{% if c.get("countryName") %}, {{ c["countryName"] }}{% endif %}
            </span>
            {% if c.get("_ok") %}
              — lat {{ c["lat"] }}, lon {{ c["lng"] }}
              <form method="POST" action="{{ url_for('select_city') }}" class="inline">
                <input type="hidden" name="name" value="{{ c['name'] }}">
                <input type="hidden" name="adminName1" value="{{ c.get('adminName1','') }}">
                <input type="hidden" name="countryName" value="{{ c.get('countryName','') }}">
                <input type="hidden" name="lat" value="{{ c['lat'] }}">
                <input type="hidden" name="lng" value="{{ c['lng'] }}">
                <button type="submit">Use this</button>
              </form>
            {% endif %}
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

    <input type="hidden" name="lat" value="{{ selected_city['lat'] if selected_city else '' }}">
    <input type="hidden" name="lng" value="{{ selected_city['lng'] if selected_city else '' }}">
    <button type="submit">Compute</button>
  </form>

  {% if page_error %}
    <p class="err">{{ page_error }}</p>
  {% endif %}

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

# ------------------ GeoNames helpers ------------------
class GeoNamesError(RuntimeError):
    pass

def _check_geonames_status(json_obj):
    st = json_obj.get("status")
    if st:
        msg = st.get("message", "GeoNames error")
        code = st.get("value", "")
        raise GeoNamesError(f"{msg} (status {code})")

def geonames_search(q: str, country: str | None = None):
    url = f"{GEONAMES_BASE}/searchJSON"
    params = {
        "q": q,
        "maxRows": 10,
        "username": GEONAMES_USERNAME,
        "featureClass": "P",
        "orderby": "relevance",
    }
    if country:
        params["country"] = country
    r = requests.get(url, params=params, timeout=12)
    r.raise_for_status()
    data = r.json()
    _check_geonames_status(data)
    return [
        {
            "name": g.get("name", ""),
            "countryName": g.get("countryName", ""),
            "adminName1": g.get("adminName1", ""),
            "lat": str(g.get("lat")),
            "lng": str(g.get("lng")),
            "_ok": True,
        }
        for g in data.get("geonames", [])
    ]

def geonames_timezone(lat: float, lng: float) -> str:
    url = f"{GEONAMES_BASE}/timezoneJSON"
    params = {"lat": lat, "lng": lng, "username": GEONAMES_USERNAME}
    r = requests.get(url, params=params, timeout=12)
    r.raise_for_status()
    data = r.json()
    _check_geonames_status(data)
    tzid = data.get("timezoneId")
    if not tzid:
        raise GeoNamesError("timezoneId missing from GeoNames")
    return tzid

# ------------------ Utilities ------------------

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

# ------------------ Routes ------------------
@app.route("/", methods=["GET","POST"])
def index():
    q = request.args.get("q", "").strip() if request.method == "GET" else ""
    action = request.args.get("action") if request.method == "GET" else None

    city_results = None
    selected_city = None
    results = None
    page_error = None

    date_val = time_val = tzid = None
    sidereal = False
    fb_offset_val = None

    # City search
    if request.method == "GET" and action == "search" and q:
        try:
            hint = "US" if any(tag in q.upper() for tag in [", KY", ", USA", " USA"]) else None
            city_results = geonames_search(q, country=hint)
        except Exception as e:
            city_results = [{
                "name": f"GeoNames error: {e}",
                "countryName": "", "adminName1": "", "lat": "", "lng": "",
                "_ok": False,
            }]

    if request.method == "POST":
        try:
            date_val = (request.form.get("date") or "").strip()
            time_val = (request.form.get("time") or "").strip()
            tzid = (request.form.get("tzid") or "UTC").strip()
            sidereal = (request.form.get("sidereal") == "fb")
            try:
                fb_offset_val = float((request.form.get("fb_offset") or "").strip())
            except Exception:
                fb_offset_val = DEFAULT_FB_EXTRA_OFFSET_DEG

            # If hidden lat/lon present and tzid missing/AUTO, try GeoNames timezone
            lat_raw = request.form.get("lat")
            lng_raw = request.form.get("lng")
            if (not tzid or tzid.upper() == "AUTO") and lat_raw and lng_raw:
                try:
                    tzid = geonames_timezone(float(lat_raw), float(lng_raw))
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
                ayan_used = f"{ayan:.6f}"
            else:
                ayan = 0.0
                ayan_used = None

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
            return render_template_string(
                HTML,
                q=None, city_results=None, selected_city=selected_city,
                results=results, date=date_val, time=time_val, tzid=tzid,
                sidereal=sidereal, fb_offset=fb_offset_val,
                local_str=local_dt.strftime("%Y-%m-%d %H:%M"),
                utc_str=utc_dt.strftime("%Y-%m-%d %H:%M"),
                jd=f"{jd:.5f}", ayan_used=ayan_used,
                page_error=None
            )
        except Exception as e:
            page_error = f"Input error: {e}"

    # Default GET view
    return render_template_string(
        HTML,
        q=q, city_results=city_results, selected_city=selected_city,
        results=None, date="1962-07-02", time="23:33", tzid="America/New_York",
        sidereal=True, fb_offset=DEFAULT_FB_EXTRA_OFFSET_DEG,
        local_str="", utc_str="", jd="", ayan_used=None, page_error=page_error
    )

@app.route("/select_city", methods=["POST"])
def select_city():
    try:
        name = request.form.get("name", "")
        admin = request.form.get("adminName1", "")
        country = request.form.get("countryName", "")
        lat_raw = (request.form.get("lat") or "").strip()
        lng_raw = (request.form.get("lng") or "").strip()
        if not lat_raw or not lng_raw:
            raise ValueError("Missing lat/lon from selection")

        lat = float(lat_raw); lng = float(lng_raw)
        try:
            tzid = geonames_timezone(lat, lng)
        except Exception:
            tzid = "UTC"

        selected = {
            "label": f"{name}{', ' + admin if admin else ''}{', ' + country if country else ''}",
            "lat": lat, "lng": lng, "tzid": tzid
        }
        return render_template_string(
            HTML,
            q=None, city_results=None, selected_city=selected,
            results=None, date="1962-07-02", time="23:33",
            tzid=tzid, sidereal=True, fb_offset=DEFAULT_FB_EXTRA_OFFSET_DEG,
            local_str="", utc_str="", jd="", ayan_used=None, page_error=None
        )
    except Exception as e:
        err_row = [{"name": f"Selection error: {e}", "countryName":"", "adminName1":"", "lat":"", "lng":"", "_ok": False}]
        return render_template_string(
            HTML,
            q=None, city_results=err_row, selected_city=None,
            results=None, date="1962-07-02", time="23:33",
            tzid="America/New_York", sidereal=True, fb_offset=DEFAULT_FB_EXTRA_OFFSET_DEG,
            local_str="", utc_str="", jd="", ayan_used=None, page_error=None
        )

if __name__ == "__main__":
    # Bind to 0.0.0.0:8000 for Render/Docker
    app.run(host="0.0.0.0", port=8000)
