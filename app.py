# app.py — AgroSmart with Capacitive Soil Probe + DHT fallback
# - Prefers soil moisture (soil_pct). Falls back to air humidity (humidity_pct / moisture_pct).
# - ONLINE/STALE/OFFLINE status pill, thresholds & controls preserved.

# --- Safety net: ensure firebase-admin is available in Streamlit Cloud ---
try:
    import firebase_admin  # noqa: F401
except ModuleNotFoundError:
    import subprocess, sys
    subprocess.check_call([sys.executable, "-m", "pip", "install", "firebase-admin==6.5.0"])
    import firebase_admin
# -------------------------------------------------------------------------

import time
from datetime import datetime, timezone
import pandas as pd
import altair as alt
import streamlit as st

import firebase_admin
from firebase_admin import credentials, db


# ----------------------------- Firebase Init -----------------------------
def init_firebase():
    if firebase_admin._apps:
        return
    fb = st.secrets["firebase"]
    cred_dict = {
        "type": fb.get("type"),
        "project_id": fb.get("project_id"),
        "private_key_id": fb.get("private_key_id"),
        "private_key": fb.get("private_key").replace("\\n", "\n")
            if isinstance(fb.get("private_key"), str) else fb.get("private_key"),
        "client_email": fb.get("client_email"),
        "client_id": fb.get("client_id"),
        "auth_uri": fb.get("auth_uri"),
        "token_uri": fb.get("token_uri"),
        "auth_provider_x509_cert_url": fb.get("auth_provider_x509_cert_url"),
        "client_x509_cert_url": fb.get("client_x509_cert_url"),
        "universe_domain": fb.get("universe_domain"),
    }
    cred = credentials.Certificate(cred_dict)
    firebase_admin.initialize_app(cred, {"databaseURL": fb.get("database_url")})


# ----------------------------- Helpers -----------------------------
def ts_to_dt(ts):
    try:
        if ts is None or isinstance(ts, dict):
            return None
        if isinstance(ts, str):
            ts = ts.strip()
            if not ts:
                return None
            ts = float(ts)
        ts = float(ts)
        if ts > 1e12:
            ts = ts / 1000.0
        return datetime.fromtimestamp(ts, tz=timezone.utc).astimezone()
    except Exception:
        return None


def pull_zone(zone_id="Z1"):
    z = db.reference("/zones").child(zone_id).get() or {}
    return z


def pull_logs(zone_id="Z1", limit=300):
    """Return df with dt + soil_pct + humidity_pct + temp_c (any may be NaN)."""
    logs = db.reference("/logs").child(zone_id).get() or {}
    rows = []
    if isinstance(logs, dict):
        for _, v in logs.items():
            if isinstance(v, dict):
                rows.append({
                    "ts": v.get("ts"),
                    # accept multiple possible field names for compatibility
                    "soil_pct": v.get("soil_pct", v.get("soil_moisture_pct")),
                    "humidity_pct": v.get("humidity_pct", v.get("moisture_pct")),
                    "temp_c": v.get("temp_c"),
                })
    df = pd.DataFrame(rows)
    if not df.empty:
        df["dt"] = df["ts"].apply(ts_to_dt)
        df = df.dropna(subset=["dt"]).sort_values("dt")
        if len(df) > limit:
            df = df.iloc[-limit:]
    return df


def write_command(zone_id, cmd):
    db.reference("/zones").child(zone_id).update({
        "command": cmd,
        "command_ts": int(time.time() * 1000)
    })


def get_thresholds(zone_id):
    m = db.reference("/meta").child(zone_id).get() or {}
    theta_start = int(m.get("theta_start_pct", 30))
    theta_stop  = int(m.get("theta_stop_pct", 45))
    return theta_start, theta_stop


def write_thresholds(zone_id, start_pct, stop_pct):
    db.reference("/meta").child(zone_id).update({
        "theta_start_pct": int(start_pct),
        "theta_stop_pct": int(stop_pct),
        "updated_ts": int(time.time() * 1000)
    })


# --------- Device status pill ----------
def make_status_pill(last_dt, heartbeat_s=45, stale_s=240):
    now = datetime.now().astimezone()
    if not last_dt:
        return '<span class="pill bad"><span class="dot"></span> OFFLINE</span>', "offline"
    age = (now - last_dt).total_seconds()
    if age <= heartbeat_s:
        txt = f"ONLINE · {int(age)}s ago"; cls = "ok"; state = "online"
    elif age <= stale_s:
        m, s = int(age // 60), int(age % 60)
        txt = f"STALE · {m}m {s}s ago"; cls = "warn"; state = "stale"
    else:
        m = int(age // 60); txt = f"OFFLINE · {m}m ago"; cls = "bad"; state = "offline"
    html = f'<span class="pill {cls}"><span class="dot"></span> {txt}</span>'
    return html, state


# ----------------------------- Theming -----------------------------
def inject_css(dark_mode: bool):
    if dark_mode:
        st.markdown("""
        <style>
          div[data-testid="stDecoration"] { display: none !important; }
          header[data-testid="stHeader"] { display: none !important; }
          :root{
            --bg:#0e1117; --panel:#151923; --muted:#9ca3af; --text:#e5e7eb;
            --accent:#22c55e; --border:#2a2f3a; --border-strong:#3b4252;
          }
          .stApp{background:var(--bg); color:var(--text);}
          [data-testid="stSidebar"]{background:#0c0f14;}
          h1,h2,h3,h4{color:var(--text) !important; opacity:.95;}
          [data-testid="stMetricValue"]{color:var(--text) !important;}
          [data-testid="stMetricLabel"]{color:var(--muted) !important;}
          .stButton>button{
            background:var(--panel) !important; color:var(--text) !important;
            border:1px solid var(--border) !important; border-radius:10px !important;
          }
          .stButton>button:hover{border-color:var(--accent) !important; color:var(--accent) !important;}
          .stNumberInput input, .stTextInput input, .stSelectbox [role="combobox"]{
            background:var(--panel) !important; color:var(--text) !important;
            border:1px solid var(--border) !important; border-radius:10px !important;
          }
          .stAlert{border-radius:10px !important;}
          /* status pill */
          .pill{display:inline-flex;align-items:center;gap:8px;padding:6px 10px;border-radius:999px;font-weight:600;font-size:.9rem;border:1px solid var(--border);}
          .pill .dot{width:8px;height:8px;border-radius:50%;background:currentColor;display:inline-block;}
          .pill.ok{background:rgba(34,197,94,.12);color:#22c55e;border-color:rgba(34,197,94,.35);}
          .pill.warn{background:rgba(245,158,11,.12);color:#f59e0b;border-color:rgba(245,158,11,.35);}
          .pill.bad{background:rgba(239,68,68,.12);color:#ef4444;border-color:rgba(239,68,68,.35);}
        </style>
        """, unsafe_allow_html=True)
    else:
        st.markdown("""
        <style>
          div[data-testid="stDecoration"] { display: none !important; }
          header[data-testid="stHeader"] { display: none !important; }
          :root{
            --bg:#ffffff; --panel:#ffffff; --muted:#6b7280; --text:#111827;
            --accent:#16a34a; --border:#e5e7eb; --border-strong:#d1d5db;
          }
          .stApp{background:var(--bg); color:var(--text);}
          [data-testid="stSidebar"]{background:#f8fafc;}
          h1,h2,h3,h4{color:var(--text) !important;}
          .stButton>button{background:#fff !important; color:#111827 !important; border:1px solid var(--border) !important; border-radius:10px !important;}
          .stNumberInput input, .stTextInput input, .stSelectbox [role="combobox"]{background:#fff !important; color:#111827 !important; border:1px solid var(--border) !important; border-radius:10px !important;}
          /* status pill */
          .pill{display:inline-flex;align-items:center;gap:8px;padding:6px 10px;border-radius:999px;font-weight:600;font-size:.9rem;border:1px solid var(--border);}
          .pill .dot{width:8px;height:8px;border-radius:50%;background:currentColor;display:inline-block;}
          .pill.ok{background:rgba(34,197,94,.12);color:#16a34a;border-color:rgba(34,197,94,.35);}
          .pill.warn{background:rgba(245,158,11,.12);color:#b45309;border-color:rgba(245,158,11,.35);}
          .pill.bad{background:rgba(239,68,68,.12);color:#b91c1c;border-color:rgba(239,68,68,.35);}
        </style>
        """, unsafe_allow_html=True)


def theme_chart(chart: alt.Chart, dark_mode: bool) -> alt.Chart:
    bg = "#0e1117" if dark_mode else "#ffffff"
    axis_label = "#e5e7eb" if dark_mode else "#111827"
    axis_domain = "#3b4252" if dark_mode else "#d1d5db"
    grid_opacity = 0.12 if dark_mode else 0.25
    return (chart.configure(background=bg).configure_view(stroke=None)
                 .configure_axis(labelColor=axis_label, titleColor=axis_label,
                                 domainColor=axis_domain, tickColor=axis_domain,
                                 gridOpacity=grid_opacity))


# ----------------------------- UI -----------------------------
st.set_page_config(page_title="AgroSmart", page_icon="🌱", layout="wide")
st.title("🌱 AgroSmart — Smart Irrigation")

init_firebase()

# Sidebar: Dark first
dark = st.sidebar.toggle("🌙 Dark mode", value=True)
inject_css(dark)

# Sidebar: zone + options
zone_id = st.sidebar.selectbox("Select Zone", ["Z1"], index=0)
show_humidity_overlay = st.sidebar.checkbox("Overlay air humidity (DHT) on soil chart", value=True)
auto_refresh = st.sidebar.checkbox("Auto-refresh (5s)", value=True)
if auto_refresh:
    try:
        st.query_params.update({"refresh": str(int(time.time()))})
    except Exception:
        pass

colA, colB = st.columns([2, 1])

with colA:
    st.subheader(f"Zone {zone_id} — Live Readings")

    z = pull_zone(zone_id)
    # Prefer soil probe for moisture; keep air humidity too (backward compatible)
    soil_pct = z.get("soil_pct", z.get("soil_moisture_pct"))
    humidity_pct = z.get("humidity_pct", z.get("moisture_pct"))  # DHT humidity if sent
    temp_c = z.get("temp_c")
    valve_state = z.get("valve_state", "UNKNOWN")
    command = z.get("command", "AUTO")
    last_ts = z.get("last_ts")
    last_dt = ts_to_dt(last_ts)
    last_seen = last_dt.strftime("%Y-%m-%d %H:%M:%S") if last_dt else "—"

    # Use soil moisture if available; else fall back to air humidity for the KPI
    moisture_for_kpi = soil_pct if soil_pct is not None else humidity_pct

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Soil moisture (%)" if soil_pct is not None else "Humidity / Moisture (%)",
              f"{moisture_for_kpi if moisture_for_kpi is not None else '—'}")
    k2.metric("Air Temp (°C)", f"{temp_c if temp_c is not None else '—'}")
    k3.metric("Valve (simulated)", valve_state)
    k4.metric("Mode", command)

    # Status pill
    pill_html, _status = make_status_pill(last_dt, heartbeat_s=45, stale_s=240)
    c_left, c_right = st.columns([1, 1])
    with c_left:
        st.caption(f"Last seen: {last_seen}")
    with c_right:
        st.markdown(f'<div style="text-align:right">{pill_html}</div>', unsafe_allow_html=True)

    # Charts
    df = pull_logs(zone_id, limit=300)
    if not df.empty:
        # Build soil line (preferred)
        layers = []
        if "soil_pct" in df and df["soil_pct"].notna().any():
            soil_line = alt.Chart(df).mark_line().encode(
                x=alt.X("dt:T", title="Time"),
                y=alt.Y("soil_pct:Q", title="Soil Moisture (%)"),
                tooltip=[alt.Tooltip("dt:T", title="Time"),
                         alt.Tooltip("soil_pct:Q", title="Soil (%)")]
            ).properties(height=260)
            layers.append(soil_line)

        # Optional DHT overlay
        if show_humidity_overlay and "humidity_pct" in df and df["humidity_pct"].notna().any():
            hum_line = alt.Chart(df).mark_line(strokeDash=[4,3]).encode(
                x=alt.X("dt:T", title="Time"),
                y=alt.Y("humidity_pct:Q", title=""),
                tooltip=[alt.Tooltip("dt:T", title="Time"),
                         alt.Tooltip("humidity_pct:Q", title="Air Humidity (%)")]
            )
            layers.append(hum_line)

        if layers:
            chart = alt.layer(*layers)
            st.altair_chart(theme_chart(chart, dark), use_container_width=True)
        else:
            st.info("No soil or humidity data yet for chart.")

        # Temperature chart (unchanged)
        if "temp_c" in df and df["temp_c"].notna().any():
            t_chart = alt.Chart(df).mark_line().encode(
                x=alt.X("dt:T", title="Time"),
                y=alt.Y("temp_c:Q", title="Air Temperature (°C)")
            ).properties(height=200)
            st.altair_chart(theme_chart(t_chart, dark), use_container_width=True)
    else:
        st.info("No logs yet. Once the ESP8266 starts sending data, charts will appear here.")

with colB:
    st.subheader("Controls")

    c1, c2, c3 = st.columns(3)
    if c1.button("OPEN"):
        write_command(zone_id, "OPEN"); st.success("Command sent: OPEN")
    if c2.button("CLOSE"):
        write_command(zone_id, "CLOSE"); st.success("Command sent: CLOSE")
    if c3.button("AUTO"):
        write_command(zone_id, "AUTO"); st.success("Command sent: AUTO")

    st.markdown("---")
    st.subheader("Moisture Thresholds (AUTO mode)")

    theta_start, theta_stop = get_thresholds(zone_id)
    ns = st.number_input("Start when moisture < (%)", min_value=5, max_value=80, value=int(theta_start), step=1)
    ne = st.number_input("Stop when moisture ≥ (%)", min_value=10, max_value=90, value=int(theta_stop), step=1)
    if st.button("Save thresholds"):
        if ns < ne:
            write_thresholds(zone_id, ns, ne); st.success("Thresholds updated.")
        else:
            st.error("Start threshold must be less than Stop threshold.")

    st.markdown("---")
    # Threshold advice uses soil when available
    moisture_now = soil_pct if soil_pct is not None else humidity_pct
    if (moisture_now is not None) and (theta_start is not None) and (moisture_now < theta_start):
        st.warning("Below start threshold — irrigation may be needed.")
    elif (moisture_now is not None) and (theta_stop is not None) and (moisture_now >= theta_stop):
        st.success("At/above stop threshold — likely sufficient.")

# Auto-refresh loop
if auto_refresh:
    time.sleep(5)
    st.rerun()
