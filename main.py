from __future__ import annotations
from flask import Flask, request, render_template_string, url_for
from zoneinfo import ZoneInfo
import datetime as dt
import os, requests, swisseph as swe

app = Flask(__name__)

# ---------- Config ----------
GEONAMES_USERNAME = os.getenv("GEONAMES_USERNAME") or "newastologyemerging"  # or require env-only
GEONAMES_BASE = "http://api.geonames.org"  # free tier requires http
DEFAULT_TZID = "America/New_York"
DEFAULT_USE_FIXED = True          # matches Astro.com for 1962
DEFAULT_FIXED_UTC_OFFSET = -5.0   # hours (EST)
DEFAULT_FB_EXTRA_OFFSET_DEG = 0.0 # pure Fagan/Bradley

PLANETS = [
    ("Sun", swe.SUN), ("Moon", swe.MOON), ("Mercury", swe.MERCURY),
    ("Venus", swe.VENUS), ("Mars", swe.MARS), ("Jupiter", swe.JUPITER),
    ("Saturn", swe.SATURN), ("Uranus", swe.URANUS), ("Neptune", swe.NEPTUNE),
    ("Pluto", swe.PLUTO),
]

# ---------- Templates ----------
HTML = """
<!doctype html><html><head><meta charset="utf-8"><title>Planet Positions</title>
<style>
 body{font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif;max-width:980px;margin:32px auto;padding:0 16px}
 .row{display:flex;gap:12px;flex-wrap:wrap;align-items:center;margin:.35rem 0}
 label{min-width:140px} input{padding:.4rem .55rem} button{padding:.5rem .8rem;cursor:pointer}
 table{width:100%;border-collapse:collapse;margin-top:12px}
 th,td{border:1px solid #ddd;padding:.5rem;text-align:left}
 .muted{color:#666}.err{color:#b00020}.card{border:1px solid #ddd;border-radius:8px;padding:10px;margin:10px 0}
</style></head><body>
<h1>Planet Positions — Tropical + Fagan/Bradley</h1>
<p class="muted">Enter local date/time. We compute <b>Tropical</b> and <b>Sidereal (F/B)</b> side-by-side. Use a fixed UTC offset (no DST) to match Astro.com in 1962.</p>

<form method="GET" action="/" class="row" style="align-items:flex-end">
  <div><label for="q">City search (GeoNames)</label><input id="q" name="q" placeholder="Fort Knox, KY" value="{{ q or '' }}"></div>
  <div><button type="submit" name="action" value="search">Search</button>
