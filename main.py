from __future__ import annotations
from flask import Flask, request, render_template_string, url_for
from zoneinfo import ZoneInfo
import datetime as dt
import os, requests, swisseph as swe

app = Flask(__name__)

# ---- Config ----
GEONAMES_USERNAME = os.getenv("GEONAMES_USERNAME", "newastologyemerging")
GEONAMES_BASE = "http://api.geonames.org"  # free tier uses HTTP
DEFAULT_TZID = "America/New_York"
DEFAULT_USE_FIXED = True          # mimic Astro.com for 1962
DEFAULT_FIXED_UTC_OFFSET = -5.0   # EST -> UT = local + 5h
DEFAULT_FB_EXTRA_OFFSET_DEG = 0.0 # pure Fagan/Bradley

PLANETS = [
    ("Sun", swe.SUN), ("Moon", swe.MOON), ("Mercury", swe.MERCURY),
    ("Venus", swe.VENUS), ("Mars", swe.MARS), ("Jupiter", swe.JUPITER),
    ("Saturn", swe.SATURN), ("Uranus", swe.URANUS),
    ("Neptune", swe.NEPTUNE), ("Pluto", swe.PLUTO),
]

# ---- Template (use triple single quotes to avoid """ issues) ----
HTML = '''
<!doctype html><html><head><meta charset="utf-8">
<title>Planet Positions — Tropical + Fagan/Bradley</title>
<style>
 body{font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif;max-width:980px;margin:32px auto;padding:0 16px}
 .row{display:flex;gap:12px;flex-wrap:wrap;align-items:center;margin:.35rem 0}
 label{min-width:140px} input{padding:.4rem .55rem} button{padding:.5rem .8rem;cursor:pointer}
 table{width:100%;border-collapse:collapse;margin-top:12px}
 th,td{border:1px solid #ddd;padding:.5rem;text-align:left}
 .muted{color:#666}.err{color:#b00020}.card{border:1px solid #ddd;border-radius:8px;padding:10px;margin:10px 0}
</style></head><body>
<h1>Planet Positions</h1>
<p class="muted">Enter local date/time. We compute <b>Tropical</b> and <b>Sidereal (Fagan/Bradley)</b> side-by-side. Use a fixed UTC offset (no DST) to match Astro.com in 1962.</p>

<form method="POST" class="row" style="align-items:flex-end">
  <div><label>Date (YYYY-MM-DD)</label><input name="date" value="{{ date or '1962-07-02' }}"></div>
  <div><label>Time (HH:MM)</label><input name="time" value="{{ time or '23:33' }}"></div>
  <div><label>Timezone (IANA)</label><input name="tzid" value="{{ tzid or 'America/New_York' }}"></div>
  <div><label><input type="checkbox" name="use_fixed" {% if use_fixed %}checked{% endif %}> Use fixed UTC offset (no DST)</label></div>
  <div><label>Fixed UTC offset (h)</label><input name="fixed_offset" value="{{ fixed_offset if fixed_offset is not none else '-5' }}"></div>
  <div><label>FB extra offset (°)</label><input name="fb_offset" value="{{ fb_offset if fb_offset is not none else '0.0' }}"></div>
  <button type="submit">Compute</button>
</form>

{% if page_error %}<p class="err">{{ page_error }}</p>{% endif %}

{% if results %}
<p class="muted">Local {{ local_str }} ({{ tzid_display }}) → UTC {{ utc_str }} • JD {{ jd }} • Ayanāṃśa (F/B + extra): {{ ayan_used }}°</p>
<table>
  <tr><th>Body</th><th>Tropical (°)</th><th>Tropical Sign</th><th>Sidereal F/B (°)</th><th>Sidereal Sign</th></tr>
  {% for r in results %}
    <tr><td>{{ r.name }}</td><td>{{ r.trop }}</td><td>{{ r.trop_sign }}</td><td>{{ r.sid }}</td><td>{{ r.sid_sign }}</td></tr>
  {% endfor %}
</table>
{% endif %}
</body></html>
'''

# ---- Helpers ----
def fmt_zodiac(deg: float) -> str:
    signs = ["Aries","Taurus","Gemini","Cancer","Leo","Virgo","Libra","Scorpio",
             "Sagittarius","Capricorn","Aquarius","Pisces"]
    lon = deg % 360.0
    si = int(lon // 30); x = lon - si*30
    d = int(x); m_full = (x - d) * 60
    m = int(m_full); s = int(round((m_full - m) * 60))
    if s == 60: s=0; m+=1
    if m == 60: m=0; d+=1
    return f"{d:02d}°{m:02d}'{s:02d}\" {signs[si]}"

@app.route("/", methods=["GET","POST"])
def index():
    results = None; page_error = None
    date_val = time_val = None
    tzid = DEFAULT_TZID
    use_fixed = DEFAULT_USE_FIXED
    fi
