"""The screens before sign-in: sign in, sign up, forgotten password, and the two pages emailed links
open (confirm an email, choose a new password). The checks are in backend/accounts/accounts.py.

Which screen shows is kept in the session ("auth_view"); an emailed link brings its token in the page
address (?confirm=... or ?reset=...). A finished step leaves a message ("auth_note") for the sign-in screen.
"""

import streamlit as st

from backend import config
from backend.accounts import accounts, mail
from frontend.components import cookie
from frontend.components.common import google_enabled
from frontend.html import render as html
from frontend.i18n import LANGUAGES, language, t
from frontend.pages import chat

CARD_WIDTH = 440


def _go(view: str, note: str = "") -> None:
    st.session_state.auth_view = view
    st.session_state.auth_note = note


def _set_language() -> None:
    if chosen := st.session_state.get("auth-language"):
        st.session_state.language = chosen


def _link_base() -> str:
    """The app's address for links in emails, without the part after "?"."""
    return config.APP_URL or (st.context.url or "").split("?")[0]


def _errors(keys: list[str]) -> None:
    for key in keys:
        st.error(t(f"auth.error.{key}"), icon=":material/error:")


def _switch_line(question: str, button: str, view: str) -> None:
    """A centred "Don't have an account? Sign up" line."""
    with st.container(horizontal=True, horizontal_alignment="center", vertical_alignment="center", gap="small",
                      key=f"switch-{view}"):
        st.caption(question, width="content")
        st.button(button, type="tertiary", on_click=_go, args=(view,), key=f"go-{view}")


def _sign_in() -> None:
    with st.form("sign-in", border=False, enter_to_submit=True):
        name = st.text_input(t("auth.name"), icon=":material/mail:", autocomplete="username")
        password = st.text_input(t("auth.password"), type="password", icon=":material/key:",
                                 autocomplete="current-password")
        # Enter clicks a form's first button, so Sign in comes first here; theme.css shows it under the row.
        signed = st.form_submit_button(t("auth.sign_in"), type="primary", width="stretch", key="sign-in-button")
        with st.container(horizontal=True, vertical_alignment="center", key="remember-row"):
            remember = st.checkbox(t("auth.remember"), help=t("auth.remember_help"))
            st.space("stretch")
            forgot = st.form_submit_button(t("auth.forgot"), type="tertiary")
    if forgot:
        _go("forgot")
        st.rerun()
    if signed:
        result = accounts.sign_in(name, password)
        if isinstance(result, dict):
            st.session_state.account = result
            st.session_state.auth_note = ""
            if remember:
                cookie.set_token(accounts.remember(result["id"]))
            st.rerun()
        elif result == "locked":
            st.error(t("auth.error.locked", minutes=accounts.locked_minutes(name)), icon=":material/lock_clock:")
        elif result == "not_confirmed" and not mail.ready():
            _errors(["not_confirmed_owner"])
        else:
            _errors([result])

    if google_enabled():
        html.divider(t("auth.or"))
        st.button(t("auth.google"), icon=":material/login:", width="stretch", on_click=st.login, key="google")
    _switch_line(t("auth.no_account"), t("auth.sign_up"), "sign_up")


def _sign_up() -> None:
    st.subheader(t("auth.sign_up_title"), anchor=False)
    with st.form("sign-up", border=False):
        username = st.text_input(t("auth.username"), icon=":material/person:", help=t("auth.username_help"),
                                 autocomplete="username")
        email = st.text_input(t("auth.email"), type="email", icon=":material/mail:",
                              placeholder=t("auth.email_example"), autocomplete="email")
        password = st.text_input(t("auth.password"), type="password", icon=":material/key:",
                                 help=t("auth.password_help"), autocomplete="new-password")
        repeat = st.text_input(t("auth.repeat"), type="password", icon=":material/key:", autocomplete="new-password")
        created = st.form_submit_button(t("auth.create"), type="primary", width="stretch")
    if created:
        errors = accounts.sign_up(username, email, password, repeat, _link_base(), language())
        if errors:
            _errors(errors)
        else:
            note = t("auth.check_inbox", email=email.strip()) if mail.ready() else t("auth.waiting_owner")
            _go("sign_in", note)
            st.rerun()
    _switch_line(t("auth.have_account"), t("auth.sign_in"), "sign_in")


def _forgot() -> None:
    st.subheader(t("auth.forgot_title"), anchor=False)
    if not mail.ready():
        st.info(t("auth.ask_owner"), icon=":material/support_agent:")
    else:
        st.caption(t("auth.forgot_note"))
        with st.form("forgot", border=False):
            email = st.text_input(t("auth.email"), type="email", icon=":material/mail:",
                              placeholder=t("auth.email_example"), autocomplete="email")
            if st.form_submit_button(t("auth.send_link"), type="primary", width="stretch"):
                accounts.request_reset(email, _link_base(), language())
                st.success(t("auth.link_sent"), icon=":material/mark_email_read:")  # the same for any email
    st.button(t("auth.back"), icon=":material/arrow_back:", type="tertiary", on_click=_go, args=("sign_in",))


def _new_password(token: str) -> None:
    st.subheader(t("auth.new_title"), anchor=False)
    if not accounts.token_valid(token, "reset"):
        _errors(["link_expired"])
    else:
        with st.form("new-password", border=False):
            password = st.text_input(t("auth.new_password"), type="password", icon=":material/key:",
                                     help=t("auth.password_help"), autocomplete="new-password")
            repeat = st.text_input(t("auth.repeat"), type="password", icon=":material/key:",
                                   autocomplete="new-password")
            saved = st.form_submit_button(t("auth.save_password"), type="primary", width="stretch")
        if saved:
            errors = accounts.reset_password(token, password, repeat)
            if not errors:
                del st.query_params["reset"]
                _go("sign_in", t("auth.password_saved"))
                st.rerun()
            _errors(errors)
    if st.button(t("auth.back"), icon=":material/arrow_back:", type="tertiary"):
        del st.query_params["reset"]
        _go("sign_in")
        st.rerun()


def render() -> None:
    """The sign-in screen, under the logo and tagline."""
    if token := st.query_params.get("confirm"):  # an emailed confirm link
        del st.query_params["confirm"]
        _go("sign_in", t("auth.confirmed") if accounts.confirm_email(token) else "")
        if not st.session_state.auth_note:
            st.session_state.auth_error = "link_expired"

    html.hero(chat.tagline(), centered=True)
    with st.container(horizontal_alignment="center"):
        with st.container(width=CARD_WIDTH, key="auth-card"):
            if note := st.session_state.get("auth_note"):
                st.success(note, icon=":material/check_circle:")
            if error := st.session_state.pop("auth_error", None):
                _errors([error])
            if token := st.query_params.get("reset"):
                _new_password(token)
            else:
                {"sign_up": _sign_up, "forgot": _forgot}.get(st.session_state.get("auth_view"), _sign_in)()
            st.caption(t("auth.private"), text_alignment="center")
            with st.container(horizontal_alignment="center"):
                st.segmented_control("Language", list(LANGUAGES), format_func=LANGUAGES.get, default=language(),
                                     key="auth-language", on_change=_set_language, label_visibility="collapsed")
