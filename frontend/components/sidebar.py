"""The sidebar: new chat, the pages, saved chats by day, and Settings."""

from pathlib import Path

import streamlit as st

from backend.storage import history
from frontend.components.common import current_owner, signed_in_user, start_new_chat
from frontend.pages.settings import settings_dialog

LOGO = Path(__file__).resolve().parents[1] / "assets" / "logo.svg"
MAX_CHATS_PER_GROUP = 25


def _chat_menu(chat: dict) -> None:
    """Bookmark, rename or delete one saved chat."""
    with st.popover("", icon=":material/more_horiz:", type="tertiary", key=f"menu-{chat['id']}"):
        label = "Remove bookmark" if chat["bookmarked"] else "Bookmark"
        if st.button(label, key=f"bookmark-{chat['id']}", icon=":material/bookmark:", type="tertiary"):
            history.set_bookmark(chat["id"], not chat["bookmarked"])
            st.rerun()
        title = st.text_input("Rename", value=chat["title"], key=f"title-{chat['id']}")
        if st.button("Save name", key=f"rename-{chat['id']}", icon=":material/edit:", type="tertiary"):
            history.rename_chat(chat["id"], title)
            st.rerun()
        if st.button("Delete", key=f"delete-{chat['id']}", icon=":material/delete:", type="tertiary"):
            history.delete_chat(chat["id"])
            if st.session_state.chat_id == chat["id"]:
                start_new_chat()
            st.rerun()


def render(pages: dict) -> None:
    with st.sidebar:
        st.logo(str(LOGO), size="large")
        if st.button("New chat", icon=":material/edit_square:", type="tertiary"):
            start_new_chat()
            st.switch_page(pages["chat"])
        st.page_link(pages["trips"], label="My trips", icon=":material/luggage:")
        st.page_link(pages["benchmarks"], label="Benchmarks", icon=":material/leaderboard:")
        st.page_link(pages["dashboard"], label="Dashboard", icon=":material/speed:")
        st.page_link(pages["how"], label="How it answers", icon=":material/account_tree:")

        for group, chats in history.group_chats(history.list_chats(current_owner())).items():
            st.caption(group)
            for chat in chats[:MAX_CHATS_PER_GROUP]:
                name, menu = st.columns([6, 1], gap="small", vertical_alignment="center")
                current = chat["id"] == st.session_state.chat_id
                if name.button(chat["title"], key=f"open-{chat['id']}", type="secondary" if current else "tertiary",
                               width="stretch", help=chat["title"]):
                    st.switch_page(pages["chat"], query_params={"chat": chat["id"]})
                with menu:
                    _chat_menu(chat)

        with st.container(key="sidebar-footer"):  # pinned to the bottom by frontend/html/theme.css
            st.divider()
            if user := signed_in_user():
                st.caption(f"Signed in as {user['name'] or user['email']}")
                st.button("Sign out", icon=":material/logout:", type="tertiary", on_click=st.logout)
            else:
                st.caption("Saved on this computer.")
            # The pop-up opens from the main area (app.py), as dialogs don't open from inside the sidebar.
            st.button("Settings", icon=":material/settings:", type="tertiary",
                      on_click=lambda: st.session_state.update(open_settings=True))


def open_settings_if_asked() -> None:
    if st.session_state.pop("open_settings", False):
        settings_dialog()
