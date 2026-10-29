"""The "Remember me" cookie. Streamlit reads cookies (st.context.cookies) but can't set them, so a tiny
custom component sets or deletes it in the browser with one line of JavaScript.

What the cookie should be is kept in the session ("cookie": the token to set, or "" to delete) and
drawn on every run, so a rerun right after signing in or out can't skip it. The component has no
visible part; frontend/html/theme.css hides its container.
"""

import streamlit as st

NAME = "tripmate_remember"
DAYS = 30

# The token only has letters, digits, "-" and "_" (secrets.token_urlsafe), checked again here, so
# it can't change the rest of the cookie. Secure is left out on http://localhost, where it would be refused.
_JS = """
export default function ({ data }) {
  const token = data && data.token;
  const secure = location.protocol === "https:" ? "; Secure" : "";
  if (token && /^[A-Za-z0-9_-]+$/.test(token)) {
    document.cookie = `${data.name}=${token}; max-age=${data.seconds}; path=/; SameSite=Lax${secure}`;
  } else {
    document.cookie = `${data.name}=; max-age=0; path=/; SameSite=Lax${secure}`;
  }
}
"""
_cookie_js = st.components.v2.component("tripmate_cookie", html="<span></span>", js=_JS)


def remembered_token() -> str:
    """The token in this browser's cookie (as it was when the page was opened), or ""."""
    value = st.context.cookies.get(NAME, "")
    return value if isinstance(value, str) else ""  # AppTest has no real cookies


def set_token(token: str) -> None:
    st.session_state.cookie = token


def delete() -> None:
    st.session_state.cookie = ""


def sync() -> None:
    """Draws the component when the session has something to set or delete."""
    if "cookie" in st.session_state:
        with st.container(key="cookie-sync"):
            _cookie_js(data={"name": NAME, "token": st.session_state.cookie, "seconds": DAYS * 86400},
                       key="tripmate-cookie")
