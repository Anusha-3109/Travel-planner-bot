"""TripMate: a Streamlit travel planning chatbot with RAG and tool calling.

Run with:  streamlit run app.py

The pages live in frontend/pages/: the chat (main page), My trips, Benchmarks,
Dashboard and How it answers, with Settings as a pop-up. Chats, trips and the
request log are saved by history.py, and the open chat's id is kept in the page
address so a refresh reopens it. With Google sign-in set up ([auth] in
.streamlit/secrets.toml), everyone signs in and sees only their own chats and
trips; without it (on a computer), the app opens straight away.
"""

import hmac

import streamlit as st

from backend import config
from backend.security.redaction import protect_logs
from backend.storage import history
from frontend.components import sidebar
from frontend.components.common import (
    PAGES,
    current_owner,
    init_state,
    prepare_index,
    sign_in_enabled,
    signed_in_user,
    sync_chat_with_url,
)
from frontend.html import render
from frontend.pages import benchmarks, chat, dashboard, how_it_answers
from frontend.pages import trips as trips_pages

st.set_page_config(page_title="TripMate travel planner", page_icon="✈️", layout="wide")
protect_logs()


def password_ok() -> bool:
    """The password screen for a deployed copy (APP_PASSWORD). Without a password set, it's skipped."""
    if not config.APP_PASSWORD or st.session_state.get("signed_in"):
        return True
    st.title("TripMate")
    with st.form("password"):
        password = st.text_input("Password", type="password")
        if st.form_submit_button("Open TripMate", type="primary"):
            if hmac.compare_digest(password.encode(), config.APP_PASSWORD.encode()):
                st.session_state.signed_in = True
                st.rerun()
            st.error("Wrong password.")
    return False


def signed_in() -> bool:
    """Google sign-in when it's set up, otherwise the password screen, otherwise straight in."""
    if not sign_in_enabled():
        return password_ok()
    if user := signed_in_user():
        # The first time the author signs in, what was saved before sign-in becomes theirs.
        if (config.OWNER_EMAIL and not st.session_state.get("claimed")
                and user["email"].strip().lower() == config.OWNER_EMAIL.strip().lower()):
            history.claim_local_data(current_owner())
            st.session_state.claimed = True
        return True
    render.theme()
    render.hero(chat.tagline())
    with st.container(horizontal_alignment="center"):
        st.button("Sign in with Google", icon=":material/login:", type="primary", on_click=st.login)
        st.caption("Your chats, trips and documents are private to your account.")
    return False


def main() -> None:
    if not signed_in():
        st.stop()
    init_state()
    if not config.OPENROUTER_API_KEY:
        st.error("OPENROUTER_API_KEY is not set. Copy `.env.example` to `.env`, add your key, and restart the app.")
        st.stop()
    try:
        prepare_index()
    except Exception as error:
        st.error(f"Couldn't build the knowledge base: {error}")
        st.stop()

    pages = {
        "chat": st.Page(chat.render, title="Chat", icon=":material/chat:", url_path="chat", default=True),
        "benchmarks": st.Page(benchmarks.render, title="Benchmarks", icon=":material/leaderboard:",
                              url_path="benchmarks"),
        "dashboard": st.Page(dashboard.render, title="Dashboard", icon=":material/speed:", url_path="dashboard"),
        "how": st.Page(how_it_answers.render, title="How it answers", icon=":material/account_tree:",
                       url_path="how-it-answers"),
        "trips": st.Page(trips_pages.my_trips, title="My trips", icon=":material/luggage:", url_path="trips"),
        "trip": st.Page(trips_pages.trip_page, title="Trip", icon=":material/map:", url_path="trip"),
    }
    PAGES.update(pages)
    page = st.navigation(list(pages.values()), position="hidden")
    if page.url_path in ("", "chat"):
        sync_chat_with_url()
    render.theme()  # frontend/html/theme.css
    sidebar.render(pages)
    sidebar.open_settings_if_asked()
    page.run()


main()
