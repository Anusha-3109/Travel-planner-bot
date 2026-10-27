"""The trip page's Budget, Packing, Journal and Documents tabs: what the traveller adds to a
saved trip. Everything is saved straight away (history.py), so it's there after a refresh.
Only "Suggest more" on the Packing tab calls the model; the rest is free.
"""

from datetime import date, datetime

import altair as alt
import pandas as pd
import streamlit as st

from backend.agent.packing import suggest_items
from backend.storage import history, trip_extras
from frontend.components.common import cost_text

PLANNED_COLOUR, SPENT_COLOUR = "#3987e5", "#d95926"
DOCUMENT_TAGS = ["Flights", "Stays", "Activities", "Insurance", "Other"]
DOCUMENT_ICONS = {"application/pdf": ":material/picture_as_pdf:"}
UPLOAD_MB = history.MAX_DOCUMENT_BYTES // (1024 * 1024)


def _days(trip: dict) -> list[tuple[int, str]]:
    """(day number, label) for each day of the trip, such as (2, "Day 2 · Tue 10 Nov")."""
    labels = []
    for day in trip.get("days") or []:
        when = f" · {date.fromisoformat(day['date']):%a %d %b}" if day.get("date") else ""
        labels.append((day["day"], f"Day {day['day']}{when}"))
    return labels


def _money(currency: str, value: float | None) -> str:
    # Escaped, because Streamlit reads text between two "$" signs as a formula.
    return "—" if value is None else f"{currency} {value:,.2f}".replace("$", r"\$")


# --- Budget ---------------------------------------------------------------------

def _budget_chart(rows: list[dict]) -> alt.Chart:
    frame = pd.DataFrame(rows).melt("Category", ["Planned", "Spent"], var_name="Amount", value_name="Value")
    frame = frame.dropna()
    return alt.Chart(frame).mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4).encode(
        x=alt.X("Category:N", title=None, sort=list(trip_extras.BUDGET_CATEGORIES), axis=alt.Axis(labelAngle=0)),
        xOffset=alt.XOffset("Amount:N", sort=["Planned", "Spent"]),
        y=alt.Y("Value:Q", title=None),
        color=alt.Color("Amount:N", title=None, scale=alt.Scale(domain=["Planned", "Spent"],
                                                                range=[PLANNED_COLOUR, SPENT_COLOUR]),
                        legend=alt.Legend(orient="top")),
        tooltip=["Category:N", "Amount:N", alt.Tooltip("Value:Q", format=",.2f")]).properties(height=240)


def budget_tab(trip: dict) -> None:
    expenses = history.list_expenses(trip["id"])
    summary = trip_extras.budget_summary(trip, expenses)
    currency = summary["currency"]
    with st.container(horizontal=True):
        if summary["budget"] is not None:
            st.metric("Budget", _money(currency, summary["budget"]), border=True)
        st.metric("Planned", _money(currency, summary["planned"]), border=True)
        st.metric("Spent", _money(currency, summary["spent"]), border=True)
        if summary["left"] is not None:
            st.metric("Left of budget" if summary["left"] >= 0 else "Over budget",
                      _money(currency, abs(summary["left"])), border=True)
        st.metric("Spent per person", _money(currency, summary["per_person"]),
                  f"{summary['people']} traveller{'s' if summary['people'] != 1 else ''}", delta_color="off",
                  delta_arrow="off", border=True)
    if summary["budget"]:
        st.progress(min(summary["spent"] / summary["budget"], 1.0),
                    text=f"{summary['spent'] / summary['budget']:.0%} of the budget spent")

    with st.form(f"expense-{trip['id']}", clear_on_submit=True, border=True):
        st.markdown("**Add an expense**")
        days = [(None, "No day")] + _days(trip)
        day, category, amount = st.columns([2, 2, 2])
        chosen_day = day.selectbox("Day", days, format_func=lambda d: d[1])
        chosen_category = category.selectbox("Category", list(trip_extras.BUDGET_CATEGORIES))
        value = amount.number_input(f"Amount ({currency})", min_value=0.0, step=1.0, format="%.2f")
        note = st.text_input("Note", placeholder="What it was for (optional)", max_chars=200)
        if st.form_submit_button("Add", icon=":material/add:", type="primary"):
            if value <= 0:
                st.error("Enter an amount above 0.")
            else:
                history.add_expense(trip["id"], chosen_category, value, chosen_day[0], note)
                st.rerun()

    st.markdown("**Planned against spent**")
    st.altair_chart(_budget_chart(summary["rows"]))
    st.caption("Planned amounts come from the saved plan's cost breakdown; Other has no planned amount.")

    if expenses:
        st.markdown("**Expenses**")
        labels = dict(_days(trip))
        for expense in expenses:
            text, remove = st.columns([12, 1], vertical_alignment="center")
            where = labels.get(expense["day"], "No day")
            text.markdown(f"{where} · {expense['category']} · **{_money(currency, expense['amount'])}**"
                          + (f" · {expense['note']}" if expense["note"] else ""))
            if remove.button("", key=f"del-expense-{expense['id']}", icon=":material/close:", type="tertiary",
                             help="Delete this expense"):
                history.delete_expense(expense["id"])
                st.rerun()


# --- Packing --------------------------------------------------------------------

def _suggest(trip: dict, names: list[str]) -> None:
    try:
        items, usage = suggest_items(trip, names, st.session_state.get("model"))
    except Exception:  # a failed model call shouldn't break the page
        st.session_state[f"packing-note-{trip['id']}"] = "The model couldn't be reached. Try again in a moment."
        return
    added = history.add_packing_items(trip["id"], [(item, "Suggested") for item in items])
    st.session_state[f"packing-note-{trip['id']}"] = (
        f"Added {added} suggested item{'s' if added != 1 else ''} · model cost {cost_text(usage.get('cost_usd'))}")


def packing_tab(trip: dict) -> None:
    items = history.list_packing_items(trip["id"])
    if not items:
        st.caption("Start with a list made for this trip: documents, clothes for the number of nights, a plug "
                   "adapter if the sockets differ from home, and items for what the plan contains.")
        if st.button("Make my packing list", icon=":material/backpack:", type="primary"):
            history.add_packing_items(trip["id"], trip_extras.packing_suggestions(trip))
            st.rerun()
        return
    packed = sum(item["packed"] for item in items)
    st.progress(packed / len(items), text=f"{packed} of {len(items)} packed")
    sections = list(dict.fromkeys(item["section"] for item in items))
    for section in sections:
        # Full width, so long items fit next to their remove button.
        with st.container(border=True):
            st.markdown(f"**{section}**")
            for item in (i for i in items if i["section"] == section):
                tick, remove = st.columns([14, 1], vertical_alignment="center")
                tick.checkbox(item["name"], value=item["packed"], key=f"pack-{item['id']}",
                              on_change=lambda i=item["id"]: history.set_packed(i, st.session_state[f"pack-{i}"]))
                if remove.button("", key=f"del-pack-{item['id']}", icon=":material/close:", type="tertiary",
                                 help="Remove from the list"):
                    history.delete_packing_item(item["id"])
                    st.rerun()

    with st.form(f"pack-add-{trip['id']}", clear_on_submit=True, border=False):
        name, section, add = st.columns([4, 2, 1], vertical_alignment="bottom")
        new = name.text_input("Add an item", max_chars=80)
        where = section.selectbox("Section", sections + [s for s in ["Other"] if s not in sections])
        if add.form_submit_button("Add", icon=":material/add:") and new.strip():
            history.add_packing_items(trip["id"], [(new, where)])
            st.rerun()
    st.button("Suggest more", icon=":material/auto_awesome:", on_click=_suggest,
              args=(trip, [item["name"] for item in items]),
              help="Asks the model for items for this trip that aren't on the list yet (about $0.001)")
    if note := st.session_state.pop(f"packing-note-{trip['id']}", None):
        st.caption(note)


# --- Journal --------------------------------------------------------------------

def _save_text(trip_id: str, day: int) -> None:
    history.save_journal(trip_id, day, text=st.session_state[f"journal-{trip_id}-{day}"])


def _save_rating(trip_id: str, day: int) -> None:
    stars = st.session_state[f"stars-{trip_id}-{day}"]
    history.save_journal(trip_id, day, rating=0 if stars is None else stars + 1)


def _photos(trip: dict, day: int) -> None:
    photos = [d for d in history.list_documents(trip["id"], day) if d["mime"].startswith("image/")]
    if photos:
        columns = st.columns(3)
        for number, photo in enumerate(photos):
            with columns[number % 3]:
                st.image(history.read_document(photo), caption=photo["name"])
    with st.form(f"photo-{trip['id']}-{day}", clear_on_submit=True, border=False):
        upload = st.file_uploader("Add a photo", type=["png", "jpg", "jpeg", "webp"], max_upload_size=UPLOAD_MB,
                                  key=f"photo-file-{trip['id']}-{day}")
        if st.form_submit_button("Add photo", icon=":material/add_a_photo:") and upload:
            try:
                history.save_document(trip["id"], upload.name, upload.getvalue(), "Journal", day)
                st.rerun()
            except ValueError as error:
                st.error(str(error))


def journal_tab(trip: dict) -> None:
    st.caption("A note and a rating for each day, saved as you type. Photos are kept with the trip.")
    journal = history.load_journal(trip["id"])
    for day, label in _days(trip):
        entry = journal.get(day, {})
        city = next((d.get("city") for d in trip["days"] if d["day"] == day), None)
        with st.container(border=True):
            st.markdown(f"**{label}**" + (f" · {city}" if city else ""))
            st.text_area("Note", value=entry.get("text", ""), key=f"journal-{trip['id']}-{day}", height=100,
                         label_visibility="collapsed", placeholder="What did you do, see and eat?",
                         on_change=_save_text, args=(trip["id"], day), max_chars=5000)
            rating, saved = st.columns([2, 3], vertical_alignment="center")
            with rating:
                st.feedback("stars", key=f"stars-{trip['id']}-{day}",
                            default=entry["rating"] - 1 if entry.get("rating") else None,
                            on_change=_save_rating, args=(trip["id"], day))
            if entry.get("updated_at"):
                saved.caption(f"Saved {datetime.fromtimestamp(entry['updated_at']):%d %b, %H:%M}")
            with st.expander("Photos"):
                _photos(trip, day)


# --- Documents ------------------------------------------------------------------

def _size(size: int) -> str:
    return f"{size / 1024 / 1024:.1f} MB" if size >= 1024 * 1024 else f"{max(size // 1024, 1)} KB"


def documents_tab(trip: dict) -> None:
    st.warning("Everyone who can open TripMate can see these files, so don't upload passports, ID or "
               "anything private. Tickets, booking confirmations and vouchers are fine.", icon=":material/lock:")
    with st.form(f"document-{trip['id']}", clear_on_submit=True, border=True):
        upload = st.file_uploader("Upload a file (PDF, PNG, JPEG or WebP, up to 5 MB)",
                                  type=["pdf", "png", "jpg", "jpeg", "webp"], max_upload_size=UPLOAD_MB)
        tag, day = st.columns(2)
        chosen_tag = tag.selectbox("Type", DOCUMENT_TAGS)
        chosen_day = day.selectbox("Day", [(None, "Whole trip")] + _days(trip), format_func=lambda d: d[1])
        if st.form_submit_button("Upload", icon=":material/upload:", type="primary") and upload:
            try:
                history.save_document(trip["id"], upload.name, upload.getvalue(), chosen_tag, chosen_day[0])
                st.rerun()
            except ValueError as error:
                st.error(str(error))

    documents = [d for d in history.list_documents(trip["id"]) if d["tag"] != "Journal"]
    if not documents:
        st.caption("No documents yet.")
        return
    labels = dict(_days(trip))
    for document in documents:
        with st.container(border=True):
            icon = DOCUMENT_ICONS.get(document["mime"], ":material/image:")
            text, get, remove = st.columns([6, 3, 1], vertical_alignment="center")
            text.markdown(f"{icon} **{document['name']}**  \n{document['tag']} · "
                          f"{labels.get(document['day'], 'Whole trip')} · {_size(document['size'])}")
            get.download_button("Open", history.read_document(document), file_name=document["name"],
                                mime=document["mime"], key=f"get-{document['id']}", icon=":material/download:",
                                on_click="ignore")
            if remove.button("", key=f"del-doc-{document['id']}", icon=":material/delete:", type="tertiary",
                             help="Delete this file"):
                history.delete_document(document["id"])
                st.rerun()
            if document["mime"].startswith("image/"):
                with st.expander("Preview"):
                    st.image(history.read_document(document))

