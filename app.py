"""TripMate: a Streamlit travel planning chatbot with RAG and tool calling.

Run with:  streamlit run app.py

The pages live in ui/: the chat (main page), Benchmarks, Dashboard and How it
answers, with Settings as a pop-up. Chats and the request log are saved on this
computer (history.py), and the open chat's id is kept in the page address so a
refresh reopens it.
"""

import streamlit as st

import config
from security.redaction import protect_logs
from ui import benchmarks, chat, dashboard, how_it_answers, sidebar, trips_pages
from ui.common import PAGES, init_state, prepare_index, sync_chat_with_url

st.set_page_config(page_title="TripMate travel planner", page_icon="✈️", layout="wide")
protect_logs()


def main() -> None:
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
    sidebar.render(pages)
    sidebar.open_settings_if_asked()
    page.run()


main()
