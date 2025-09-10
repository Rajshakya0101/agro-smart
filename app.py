# app.py — AgroSmart (ESP8266 + DHT demo) with runtime Dark Mode toggle
# - Humidity as "moisture_pct", temperature as "temp_c"
# - Firebase Admin via .streamlit/secrets.toml
# - Robust timestamp parsing (ms/s, dicts/strings)
# - Dark/Light toggle (CSS) + charts that adapt at runtime

import time
from datetime import datetime, timezone
import pandas as pd
import altair as alt
import streamlit as st

import firebase_admin
from firebase_admin import credentials, db


# ----------------------------- Firebase Init -----------------------------
def init_firebase():
    """Initialize Firebase Admin using values from st.secrets['firebase']."""
    if firebase_admin._apps:
        return
    fb = st.secrets["firebase"]  # will raise nicely if missing

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
    """Convert Firebase timestamp (ms or s; number or string) to aware datetime. Return None if invalid."""
    try:
        if ts is None:
            return None
        if isinstance(ts, dict):  # unresolved server-value like {".sv":"timestamp"}
            return None
        if isinstance(ts, str):
            ts = ts.strip()
            if not ts:
                return None
            ts = float(ts)
        ts = float(ts)
        if ts > 1e12:  # ms -> s
            ts = ts / 1000.0
        return datetime.fromtimestamp(ts, tz=timezone.utc).astimezone()
    except Exception:
        return None


def pull_zone(zone_id="Z1"):
    """Return dict for /zones/<zone_id> or {}."""
    z = db.reference("/zones").child(zone_id).get()
    return z or {}


def pull_logs(zone_id="Z1", limit=300):
    """Return DataFrame of recent /logs/<zone_id> with columns [ts, moisture_pct, temp_c, dt]."""
    logs = db.reference("/logs").child(zone_id).get() or {}
    rows = []
    if isinstance(logs, dict):
        for _, v in logs.items():
            if isinstance(v, dict):
                rows.append({
                    "ts": v.get("ts"),
                    "moisture_pct": v.get("moisture_pct"),
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
    """Write OPEN/CLOSE/AUTO to /zones/<zone_id>/command."""
    db.reference("/zones").child(zone_id).update({
        "command": cmd,
        "command_ts": int(time.time() * 1000)  # ms
    })


def get_thresholds(zone_id):
    """Read thresholds from /meta/<zone_id>, returning defaults if missing."""
    m = db.reference("/meta").child(zone_id).get() or {}
    theta_start = int(m.get("theta_start_pct", 30))
    theta_stop  = int(m.get("theta_stop_pct", 45))
    return theta_start, theta_stop


def write_thresholds(zone_id, start_pct, stop_pct):
    """Write thresholds to /meta/<zone_id>."""
    db.reference("/meta").child(zone_id).update({
        "theta_start_pct": int(start_pct),
        "theta_stop_pct": int(stop_pct),
        "updated_ts": int(time.time() * 1000)
    })


# ----------------------------- Theming (Option B) -----------------------------
def inject_css(dark_mode: bool):
    """Runtime theming: strong dark + tidy light."""
    if dark_mode:
        st.markdown("""
        <style>
          div[data-testid="stDecoration"] { display: none !important; }  /* rainbow */
          header[data-testid="stHeader"] { display: none !important; }   /* header + toolbar */
          :root{
            --bg:#0e1117; --panel:#151923; --muted:#9ca3af; --text:#e5e7eb;
            --accent:#22c55e; --border:#2a2f3a; --border-strong:#3b4252;
          }
          .stApp{background:var(--bg); color:var(--text);}
          [data-testid="stSidebar"]{background: #0c0f14;}
          h1,h2,h3,h4{color:var(--text) !important; opacity:0.95;}
          /* cards / containers */
          .stMarkdown, .stVerticalBlock, .stHorizontalBlock{ color:var(--text); }
          hr{border-color:var(--border-strong) !important;}
          /* metrics */
          [data-testid="stMetricValue"]{color:var(--text) !important;}
          [data-testid="stMetricLabel"]{color:var(--muted) !important;}
          /* buttons */
          .stButton>button{
            background: var(--panel) !important; color: var(--text) !important;
            border:1px solid var(--border) !important; border-radius:10px !important;
          }
          .stButton>button:hover{ border-color: var(--accent) !important; color: var(--accent) !important;}
          /* inputs (number/select/text) */
          .stNumberInput input, .stTextInput input, .stSelectbox [role="combobox"]{
            background: var(--panel) !important; color: var(--text) !important;
            border:1px solid var(--border) !important; border-radius:10px !important;
          }
          .stNumberInput button[kind="plain"]{ color:var(--text) !important; }
          /* alerts */
          .stAlert{ border-radius:10px !important; }
        </style>
        """, unsafe_allow_html=True)
    else:
        st.markdown("""
        <style>
          div[data-testid="stDecoration"] { display: none !important; }  /* rainbow */
          header[data-testid="stHeader"] { display: none !important; }   /* header + toolbar */
          :root{
            --bg:#ffffff; --panel:#ffffff; --muted:#6b7280; --text:#111827;
            --accent:#16a34a; --border:#e5e7eb; --border-strong:#d1d5db;
          }
          .stApp{background:var(--bg); color:var(--text);}
          [data-testid="stSidebar"]{background:#f8fafc;}
          h1,h2,h3,h4{color:var(--text) !important;}
          .stButton>button{
            background:#ffffff !important; color:#111827 !important;
            border:1px solid var(--border) !important; border-radius:10px !important;
          }
          .stNumberInput input, .stTextInput input, .stSelectbox [role="combobox"]{
            background:#ffffff !important; color:#111827 !important;
            border:1px solid var(--border) !important; border-radius:10px !important;
          }
        </style>
        """, unsafe_allow_html=True)


def theme_chart(chart: alt.Chart, dark_mode: bool) -> alt.Chart:
    bg = "#0e1117" if dark_mode else "#ffffff"
    axis_label = "#e5e7eb" if dark_mode else "#111827"
    axis_title = axis_label
    axis_domain = "#3b4252" if dark_mode else "#d1d5db"
    axis_tick = axis_domain
    grid_opacity = 0.12 if dark_mode else 0.25

    return (
        chart
        .configure(background=bg)
        .configure_view(stroke=None)
        .configure_axis(
            labelColor=axis_label, titleColor=axis_title,
            domainColor=axis_domain, tickColor=axis_tick, gridOpacity=grid_opacity
        )
    )



# ----------------------------- UI -----------------------------
st.set_page_config(page_title="AgroSmart", page_icon="🌱", layout="wide")
st.title("🌱 AgroSmart — Smart Irrigation (Jorethang)")

# Initialize Firebase (show a nice error if secrets missing)
init_firebase()

# Sidebar: Dark mode toggle comes first so styles apply to rest of page
dark = st.sidebar.toggle("🌙 Dark mode", value=False)
inject_css(dark)

# Sidebar: other controls
zone_id = st.sidebar.selectbox("Select Zone", ["Z1"], index=0)
auto_refresh = st.sidebar.checkbox("Auto-refresh (5s)", value=True)
if auto_refresh:
    # Modern API; update URL params for shareable state/cache-busting
    try:
        st.query_params.update({"refresh": str(int(time.time()))})
    except Exception:
        pass

colA, colB = st.columns([2, 1])

with colA:
    st.subheader(f"Zone {zone_id} — Live Readings")

    z = pull_zone(zone_id)
    moisture_pct = z.get("moisture_pct")  # ESP8266 sends DHT humidity here for demo
    temp_c = z.get("temp_c")
    valve_state = z.get("valve_state", "UNKNOWN")
    command = z.get("command", "AUTO")
    last_ts = z.get("last_ts")
    last_dt = ts_to_dt(last_ts)
    last_seen = last_dt.strftime("%Y-%m-%d %H:%M:%S") if last_dt else "—"

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Humidity / Moisture (%)", f"{moisture_pct if moisture_pct is not None else '—'}")
    k2.metric("Air Temp (°C)", f"{temp_c if temp_c is not None else '—'}")
    k3.metric("Valve (simulated)", valve_state)
    k4.metric("Mode", command)
    st.caption(f"Last seen: {last_seen}")

    df = pull_logs(zone_id, limit=300)
    if not df.empty:
        mo_chart = alt.Chart(df).mark_line().encode(
            x=alt.X("dt:T", title="Time"),
            y=alt.Y("moisture_pct:Q", title="Humidity / Moisture (%)")
        ).properties(height=260)
        st.altair_chart(theme_chart(mo_chart, dark), use_container_width=True)

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
        write_command(zone_id, "OPEN")
        st.success("Command sent: OPEN")
    if c2.button("CLOSE"):
        write_command(zone_id, "CLOSE")
        st.success("Command sent: CLOSE")
    if c3.button("AUTO"):
        write_command(zone_id, "AUTO")
        st.success("Command sent: AUTO")

    st.markdown("---")
    st.subheader("Moisture Thresholds (AUTO mode)")

    theta_start, theta_stop = get_thresholds(zone_id)
    ns = st.number_input("Start when moisture < (%)", min_value=5, max_value=80,
                         value=int(theta_start), step=1)
    ne = st.number_input("Stop when moisture ≥ (%)", min_value=10, max_value=90,
                         value=int(theta_stop), step=1)
    if st.button("Save thresholds"):
        if ns < ne:
            write_thresholds(zone_id, ns, ne)
            st.success("Thresholds updated.")
        else:
            st.error("Start threshold must be less than Stop threshold.")

    st.markdown("---")
    if (moisture_pct is not None) and (theta_start is not None) and (moisture_pct < theta_start):
        st.warning("Moisture is below start threshold — irrigation may be needed.")
    elif (moisture_pct is not None) and (theta_stop is not None) and (moisture_pct >= theta_stop):
        st.success("At/above stop threshold — likely sufficient.")

# Auto-refresh loop
if auto_refresh:
    time.sleep(5)
    st.rerun()
