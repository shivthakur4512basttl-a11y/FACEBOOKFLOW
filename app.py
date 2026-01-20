import streamlit as st
import os
import requests
import urllib.parse
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
import time

load_dotenv()

# --- 1. Configuration ---
INSTA_APP_ID = os.getenv("INSTA_APP_ID")
INSTA_APP_SECRET = os.getenv("INSTA_APP_SECRET")
EMBED_URL = os.getenv("INSTA_EMBED_URL")
API_VERSION = "v24.0"
INSTA_REDIRECT_URI = "https://facebookflowbasttl.streamlit.app/redirect"

# --- UTILITIES ---------------------------------------------------------------------------------
def parse_ts(ts: str):
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S%z").astimezone(timezone.utc)

def metric_value_from_insights(media_item: dict, metric_name: str) -> int:
    for m in media_item.get("insights", {}).get("data", []):
        if m.get("name") == metric_name:
            vals = m.get("values", [])
            if vals and isinstance(vals, list):
                return int(vals[0].get("value", 0) or 0)
            return int(m.get("value", 0) or 0)
    return 0

# --- FETCH MEDIA STATS (INTEGRATED FUNCTIONALITY) -----------------------------------------------
def fetch_media_totals(access_token, ig_user_id, days=90):
    cutoff_dt = datetime.now(timezone.utc) - timedelta(days=days)

    # Get media_count
    media_res = requests.get(
        f"https://graph.instagram.com/{API_VERSION}/{ig_user_id}?fields=media_count&access_token={access_token}"
    ).json()

    media_count = media_res.get("media_count", 100)
    print(f"[TERMINAL] Media Count from API = {media_count}")

    BASE_URL = (
        f"https://graph.instagram.com/{API_VERSION}/{ig_user_id}/media?"
        f"fields=id,caption,media_type,media_product_type,timestamp,permalink,"
        f"like_count,comments_count,insights.metric(views,shares,saved)"
        f"&limit={100 if media_count > 100 else media_count}"
        f"&access_token={access_token}"
    )

    totals = {
        "views": 0,
        "shares": 0,
        "saved": 0,
        "likes": 0,
        "comments": 0,
        "counted_media": 0,
        "skipped_old_media": 0,
    }

    next_url = BASE_URL
    while next_url:
        payload = requests.get(next_url).json()
        if "error" in payload:
            raise RuntimeError(payload["error"])

        for item in payload.get("data", []):
            ts = item.get("timestamp")
            if ts and parse_ts(ts) < cutoff_dt:
                totals["skipped_old_media"] += 1
                continue

            totals["counted_media"] += 1
            totals["likes"] += int(item.get("like_count", 0))
            totals["comments"] += int(item.get("comments_count", 0))
            totals["views"] += metric_value_from_insights(item, "views")
            totals["shares"] += metric_value_from_insights(item, "shares")
            totals["saved"] += metric_value_from_insights(item, "saved")

        next_url = payload.get("paging", {}).get("next")
        time.sleep(0.1)

    return totals

# --- 3. Streamlit UI ----------------------------------------------------------------------------
st.set_page_config(page_title="Instagram Pro Insights", page_icon="📊", layout="wide")
st.title("📊 Instagram Business Data Automator")

query_params = st.query_params

if "code" in query_params:

    auth_code = query_params["code"].split("#_")[0]
    print(f"\n[!] NEW AUTH CODE RECEIVED: {auth_code[:15]}...")

    with st.status("🔗 Connecting to Instagram & Fetching Data...", expanded=True) as status:

        # Exchange Code → Short Token
        token_url = "https://api.instagram.com/oauth/access_token"
        payload = {
            "client_id": INSTA_APP_ID,
            "client_secret": INSTA_APP_SECRET,
            "grant_type": "authorization_code",
            "redirect_uri": INSTA_REDIRECT_URI,
            "code": auth_code
        }
        token_res = requests.post(token_url, data=payload).json()
        short_token = token_res.get("access_token")

        if not short_token:
            st.error("❌ Token exchange failed.")
            st.write(token_res)
            st.stop()

        # Upgrade → Long Token
        ll_url = "https://graph.instagram.com/access_token"
        ll_params = {
            "grant_type": "ig_exchange_token",
            "client_secret": INSTA_APP_SECRET,
            "access_token": short_token
        }
        ll_res = requests.get(ll_url, params=ll_params).json()
        access_token = ll_res.get("access_token")

        # Profile Info
        me_url = f"https://graph.instagram.com/{API_VERSION}/me?fields=user_id,username,name,followers_count,profile_picture_url&access_token={access_token}"
        user = requests.get(me_url).json()

        user_id = user.get("user_id")
        username = user.get("username")
        name = user.get("name", "Instagram User")
        followers = user.get("followers_count", 0)
        profile_pic = user.get("profile_picture_url")

        # --- NEW: FETCH FULL MEDIA TOTALS ----------------------------------------------------------
        st.write("📸 Fetching 90-Day Media Insights...")
        media_totals = fetch_media_totals(access_token, user_id, days=90)

        status.update(label="✅ Success! Data Processed.", state="complete")

        st.divider()

        # UI: Profile Header
        c1, c2 = st.columns([1,4])
        with c1:
            st.image(profile_pic, width=120) if profile_pic else st.write("👤 No Profile Image")
        with c2:
            st.subheader(f"{name} (@{username})")
            st.write(f"**Followers:** {followers:,}")
            st.write(f"**User ID:** `{user_id}`")

        st.divider()

        # UI: 90-Day Media Totals
        st.markdown("### 🧾 90-Day Media Performance Totals")
        st.json(media_totals)

else:
    st.info("👋 Welcome! Please authorize your Instagram account.")
    st.link_button("🚀 Login & Authorize Instagram", url=EMBED_URL, use_container_width=True)
