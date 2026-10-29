"""The app's interface language: English or German (Deutsch), chosen in Settings.

The chat page, trip form, result cards, sidebar and Settings call t("key") instead of fixed text.
Benchmarks, Dashboard, How it answers and the trip pages stay in English. Texts from the tools
(prices, ratings, durations) and place names are shown as the tools and sources wrote them.
"""

import re

import streamlit as st

LANGUAGES = {"en": "English", "de": "Deutsch"}
DEFAULT_LANGUAGE = "en"

TEXTS: dict[str, dict[str, str]] = {
    # Chat page
    "tagline": {"en": "Your travel planner with live prices, costed against your budget",
                "de": "Dein Reiseplaner mit Live-Preisen, passend zu deinem Budget"},
    "mode.plan": {"en": "Plan", "de": "Planen"},
    "mode.explore": {"en": "Explore", "de": "Entdecken"},
    "mode.plan_help": {"en": "A full trip: flights, a stay, restaurants, transport, the cost against your budget "
                             "and the checks.",
                       "de": "Eine ganze Reise: Flüge, Unterkunft, Restaurants, Verkehr, die Kosten im Vergleich "
                             "zu deinem Budget und die Prüfungen."},
    "mode.explore_help": {"en": "Ideas and places: sights, restaurants and getting around. No flight or stay "
                                "searches, so it's quicker and uses no live search quota.",
                          "de": "Ideen und Orte: Sehenswürdigkeiten, Restaurants und Fortbewegung. Keine Flug- oder "
                                "Unterkunftssuche, daher schneller und ohne Live-Suchkontingent."},
    "chat.form_instead": {"en": "Fill in the trip form instead", "de": "Stattdessen das Reiseformular ausfüllen"},
    "chat.try": {"en": "Try one of these", "de": "Probier eines davon"},
    "chat.can_do": {"en": "What TripMate can do", "de": "Was TripMate kann"},
    "chat.open": {"en": "Open", "de": "Öffnen"},
    "chat.try_it": {"en": "Try it", "de": "Ausprobieren"},
    "chat.plan_trip": {"en": "Plan a trip", "de": "Reise planen"},
    "chat.save_trip": {"en": "Save as trip", "de": "Als Reise speichern"},
    "chat.tool_calls": {"en": "Tool calls ({count})", "de": "Tool-Aufrufe ({count})"},
    "chat.with_arguments": {"en": "with arguments", "de": "mit Argumenten"},
    "chat.sources": {"en": "Sources ({count})", "de": "Quellen ({count})"},
    "chat.queries": {"en": "Search queries after query translation:",
                     "de": "Suchanfragen nach der Query-Übersetzung:"},
    "chat.answered_by": {"en": "Answered by {model}", "de": "Beantwortet von {model}"},
    "chat.usage": {"en": "Tokens: {input} in · {output} out · Cost: {cost}",
                   "de": "Tokens: {input} rein · {output} raus · Kosten: {cost}"},
    "chat.too_quick": {"en": "You're sending messages too quickly. Try again in {seconds} seconds.",
                       "de": "Du sendest Nachrichten zu schnell. Versuch es in {seconds} Sekunden noch einmal."},
    "chat.planning": {"en": "Planning...", "de": "Plane..."},
    "chat.cant_answer": {"en": "Couldn't answer", "de": "Keine Antwort möglich"},
    "chat.went_wrong": {"en": "Something went wrong", "de": "Etwas ist schiefgelaufen"},
    "chat.unexpected": {"en": "Something unexpected went wrong. Please try again.",
                        "de": "Etwas Unerwartetes ist schiefgelaufen. Bitte versuch es noch einmal."},
    "chat.done": {"en": "Done · {count} tool call(s)", "de": "Fertig · {count} Tool-Aufruf(e)"},
    "cost.not_reported": {"en": "not reported", "de": "nicht gemeldet"},
    # Tiles: title and text
    "tile.ai.title": {"en": "AI planning", "de": "KI-Planung"},
    "tile.ai.text": {"en": "Describe a trip: TripMate builds a costed plan, day by day.",
                     "de": "Beschreib eine Reise: TripMate erstellt einen Plan mit Kosten, Tag für Tag."},
    "tile.days.title": {"en": "Day-by-day plan", "de": "Tagesplan"},
    "tile.days.text": {"en": "Your saved trips as timelines: times, places and prices.",
                       "de": "Deine gespeicherten Reisen als Zeitleiste: Zeiten, Orte und Preise."},
    "tile.route.title": {"en": "Route planning", "de": "Routenplanung"},
    "tile.route.text": {"en": "Every stop of a saved trip on a map.",
                        "de": "Jeder Halt einer gespeicherten Reise auf einer Karte."},
    "tile.booking.title": {"en": "Booking", "de": "Buchen"},
    "tile.booking.text": {"en": "Find Airbnbs and hotels with live prices, and book on their sites.",
                          "de": "Finde Airbnbs und Hotels mit Live-Preisen und buche auf deren Seiten."},
    "tile.discover.title": {"en": "Discover", "de": "Entdecken"},
    "tile.discover.text": {"en": "Sights, food and neighbourhoods in 245 cities.",
                           "de": "Sehenswürdigkeiten, Essen und Viertel in 245 Städten."},
    "tile.budget.title": {"en": "Budget tracker", "de": "Budget-Tracker"},
    "tile.budget.text": {"en": "Planned against spent, and spent per traveller, on a saved trip.",
                         "de": "Geplant gegen ausgegeben, und Ausgaben pro Person, für eine gespeicherte Reise."},
    "tile.packing.title": {"en": "Packing list", "de": "Packliste"},
    "tile.packing.text": {"en": "A checklist made for your trip.", "de": "Eine Checkliste für deine Reise."},
    "tile.documents.title": {"en": "Documents", "de": "Dokumente"},
    "tile.documents.text": {"en": "Tickets, bookings and vouchers, by day.",
                            "de": "Tickets, Buchungen und Gutscheine, nach Tag."},
    "tile.journal.title": {"en": "Journal", "de": "Tagebuch"},
    "tile.journal.text": {"en": "Notes, ratings and photos for each day.",
                          "de": "Notizen, Bewertungen und Fotos für jeden Tag."},
    # Trip form
    "form.title": {"en": "Plan a trip", "de": "Reise planen"},
    "form.intro": {"en": "Live flights, stays, restaurants and transport for any city worldwide, for dates from today.",
                   "de": "Live-Flüge, Unterkünfte, Restaurants und Verkehr für jede Stadt der Welt, ab heute."},
    "form.from": {"en": "From", "de": "Von"},
    "form.to": {"en": "To", "de": "Nach"},
    "form.start": {"en": "Start date", "de": "Startdatum"},
    "form.nights": {"en": "Nights", "de": "Nächte"},
    "form.travellers": {"en": "Travellers", "de": "Reisende"},
    "form.budget": {"en": "Budget ({currency})", "de": "Budget ({currency})"},
    "form.stay": {"en": "Stay", "de": "Unterkunft"},
    "form.constraints": {"en": "Constraints (optional)", "de": "Bedingungen (optional)"},
    "form.house_rule": {"en": "Stay must allow", "de": "Unterkunft muss erlauben"},
    "form.room_type": {"en": "Room type", "de": "Zimmertyp"},
    "form.cuisines": {"en": "Cuisines to include", "de": "Gewünschte Küchen"},
    "form.transport": {"en": "Transportation", "de": "Verkehrsmittel"},
    "form.no_preference": {"en": "No preference", "de": "Egal"},
    "form.submit": {"en": "Plan my trip", "de": "Meine Reise planen"},
    "rule.smoking": {"en": "smoking", "de": "Rauchen"},
    "rule.parties": {"en": "parties", "de": "Partys"},
    "rule.children under 10": {"en": "children under 10", "de": "Kinder unter 10"},
    "rule.visitors": {"en": "visitors", "de": "Besucher"},
    "rule.pets": {"en": "pets", "de": "Haustiere"},
    "room.entire room": {"en": "entire room", "de": "ganze Unterkunft"},
    "room.private room": {"en": "private room", "de": "Privatzimmer"},
    "room.shared room": {"en": "shared room", "de": "Gemeinschaftszimmer"},
    "room.not shared room": {"en": "not shared room", "de": "kein Gemeinschaftszimmer"},
    "transport.no flight": {"en": "no flight", "de": "kein Flug"},
    "transport.no self-driving": {"en": "no self-driving", "de": "kein Selbstfahren"},
    # Result cards
    "card.live": {"en": "Live", "de": "Live"},
    "card.estimate": {"en": "Estimate", "de": "Schätzung"},
    "card.snapshot": {"en": "Snapshot", "de": "Snapshot"},
    "card.flights": {"en": "Flights", "de": "Flüge"},
    "card.flight_count": {"en": "{count} flight(s)", "de": "{count} Flug/Flüge"},
    "card.from": {"en": "from {price}", "de": "ab {price}"},
    "card.more": {"en": "{count} more", "de": "{count} weitere"},
    "card.price_not_shown": {"en": "Price not shown", "de": "Preis nicht angezeigt"},
    "card.nonstop": {"en": "Nonstop", "de": "Direkt"},
    "card.stop": {"en": "1 stop", "de": "1 Zwischenstopp"},
    "card.stops": {"en": "{count} stops", "de": "{count} Zwischenstopps"},
    "card.via": {"en": "via {places}", "de": "über {places}"},
    "card.estimated_flight": {"en": "Estimated nonstop flight", "de": "Geschätzter Direktflug"},
    "card.about": {"en": "About {duration}", "de": "Etwa {duration}"},
    "card.no_price_data": {"en": "No price data", "de": "Keine Preisdaten"},
    "card.distance_note": {"en": "{km} km between the city centres; search live for real flights",
                           "de": "{km} km zwischen den Stadtzentren; such live nach echten Flügen"},
    "card.shown": {"en": "{shown} of {found} shown", "de": "{shown} von {found} angezeigt"},
    "card.no_flights": {"en": "No flights found for this date.", "de": "Keine Flüge für dieses Datum gefunden."},
    "card.by_road": {"en": "By road", "de": "Auf der Straße"},
    "card.stays": {"en": "Stays", "de": "Unterkünfte"},
    "card.to": {"en": "to", "de": "bis"},
    "card.per_night": {"en": "{price} / night", "de": "{price} / Nacht"},
    "card.total": {"en": "{price} total", "de": "{price} gesamt"},
    "card.no_rating": {"en": "No rating", "de": "Keine Bewertung"},
    "card.view_airbnb": {"en": "View on Airbnb", "de": "Auf Airbnb ansehen"},
    "card.view_hotel": {"en": "View hotel", "de": "Hotel ansehen"},
    "card.no_snapshot_price": {"en": "No price in the snapshot  \nSearch with dates for live prices",
                               "de": "Kein Preis im Snapshot  \nSuch mit Daten nach Live-Preisen"},
    "card.up_to_guests": {"en": "up to {count} guests", "de": "bis zu {count} Gäste"},
    "card.min_nights": {"en": "min {count} night(s)", "de": "mind. {count} Nacht/Nächte"},
    "card.no_stays": {"en": "No stays match these filters.", "de": "Keine Unterkünfte passen zu diesen Filtern."},
    "card.restaurants": {"en": "Restaurants", "de": "Restaurants"},
    "card.price_not_listed": {"en": "Price not listed", "de": "Preis nicht angegeben"},
    "card.open_now": {"en": "Open now", "de": "Jetzt geöffnet"},
    "card.closed_now": {"en": "Closed now", "de": "Jetzt geschlossen"},
    "card.map": {"en": "Map", "de": "Karte"},
    "card.price_na": {"en": "Price n/a", "de": "Preis k. A."},
    "card.per_person": {"en": "per person", "de": "pro Person"},
    "card.no_restaurants": {"en": "No restaurants match these filters.",
                            "de": "Keine Restaurants passen zu diesen Filtern."},
    "card.getting_around": {"en": "Getting around", "de": "Unterwegs"},
    "card.no_changes": {"en": "no changes", "de": "ohne Umstieg"},
    "card.changes": {"en": "{count} change(s)", "de": "{count} Umstieg(e)"},
    "card.steps": {"en": "Steps", "de": "Schritte"},
    "card.by_car": {"en": "By car or taxi", "de": "Mit Auto oder Taxi"},
    "card.no_taxi_fare": {"en": "Taxis: no fare data", "de": "Taxis: keine Preisdaten"},
    "card.per_vehicle": {"en": "{price} per vehicle", "de": "{price} pro Fahrzeug"},
    "card.no_fare": {"en": "No fare data", "de": "Keine Preisdaten"},
    "card.timetable": {"en": "Departure times come from the current timetable and will differ on the travel day.",
                       "de": "Abfahrtszeiten stammen aus dem aktuellen Fahrplan und weichen am Reisetag ab."},
    "card.trip_cost": {"en": "Trip cost · {count} traveller(s)", "de": "Reisekosten · {count} Reisende(r)"},
    "card.total_metric": {"en": "Total", "de": "Gesamt"},
    "card.budget": {"en": "Budget", "de": "Budget"},
    "card.left": {"en": "Left", "de": "Übrig"},
    "card.over_budget": {"en": "Over budget", "de": "Über Budget"},
    "card.within_budget": {"en": "within budget", "de": "im Budget"},
    "card.over_budget_delta": {"en": "over budget", "de": "über Budget"},
    "card.cost.transportation": {"en": "Transport", "de": "Verkehr"},
    "card.cost.accommodation": {"en": "Stay", "de": "Unterkunft"},
    "card.cost.meals": {"en": "Meals", "de": "Essen"},
    "card.cost.attractions": {"en": "Attractions", "de": "Sehenswürdigkeiten"},
    "card.unpriced": {"en": "{count} item(s) have no price data, so the real total is higher.",
                      "de": "{count} Posten ohne Preisdaten, daher ist die echte Summe höher."},
    "card.all_checks": {"en": "All checks passed", "de": "Alle Prüfungen bestanden"},
    "card.breakdown": {"en": "Cost breakdown", "de": "Kostenaufstellung"},
    "card.day": {"en": "Day {day}", "de": "Tag {day}"},
    "card.no_price": {"en": "no price", "de": "kein Preis"},
    "card.no_price_italic": {"en": "no price data", "de": "keine Preisdaten"},
    "card.options_found_one": {"en": "Options found (1 search)", "de": "Gefundene Optionen (1 Suche)"},
    "card.options_found": {"en": "Options found ({count} searches)", "de": "Gefundene Optionen ({count} Suchen)"},
    "card.in_plan": {"en": "In the plan", "de": "Im Plan"},
    "card.use_flight": {"en": "Use this flight", "de": "Diesen Flug nehmen"},
    "card.plan_flight": {"en": "Plan with this flight", "de": "Mit diesem Flug planen"},
    "card.use_stay": {"en": "Use this stay", "de": "Diese Unterkunft nehmen"},
    "card.plan_stay": {"en": "Plan with this stay", "de": "Mit dieser Unterkunft planen"},
    "card.use_route": {"en": "Use this route", "de": "Diese Route nehmen"},
    "card.add_to_plan": {"en": "Add to the plan", "de": "Zum Plan hinzufügen"},
    "card.day_label": {"en": "Day", "de": "Tag"},
    "card.meal_label": {"en": "Meal", "de": "Mahlzeit"},
    "card.add": {"en": "Add", "de": "Hinzufügen"},
    "meal.breakfast": {"en": "breakfast", "de": "Frühstück"},
    "meal.lunch": {"en": "lunch", "de": "Mittagessen"},
    "meal.dinner": {"en": "dinner", "de": "Abendessen"},
    # Follow-ups the card buttons send (the option's id keeps them exact in either language)
    "follow.use_flight": {"en": "Use {what}{leg} and update the plan and its cost.",
                          "de": "Nimm {what}{leg} und aktualisiere den Plan und seine Kosten."},
    "follow.plan_with": {"en": "Plan a trip with {what}{leg}.", "de": "Plane eine Reise mit {what}{leg}."},
    "follow.flight": {"en": "flight {numbers} ({id})", "de": "Flug {numbers} ({id})"},
    "follow.leg": {"en": " for the {route} flight on {date}", "de": " für den Flug {route} am {date}"},
    "follow.stay": {"en": "the stay {name} ({id})", "de": "die Unterkunft {name} ({id})"},
    "follow.use_stay": {"en": "Use {what} for every night instead of the current stay, and update the plan and "
                              "its cost.",
                        "de": "Nimm {what} für jede Nacht statt der jetzigen Unterkunft und aktualisiere den Plan "
                              "und seine Kosten."},
    "follow.restaurant": {"en": "Use {name} ({id}) for {meal} on day {day} and update the plan and its cost.",
                          "de": "Nimm {name} ({id}) als {meal} an Tag {day} und aktualisiere den Plan und seine "
                                "Kosten."},
    "follow.transit": {"en": "Use the public transport route {name} ({id}) for the {origin} to {destination} "
                             "transfer and update the plan and its cost.",
                       "de": "Nimm die ÖPNV-Verbindung {name} ({id}) für den Transfer von {origin} nach "
                             "{destination} und aktualisiere den Plan und seine Kosten."},
    # Sidebar
    "side.new_chat": {"en": "New chat", "de": "Neuer Chat"},
    "side.trips": {"en": "My trips", "de": "Meine Reisen"},
    "side.benchmarks": {"en": "Benchmarks", "de": "Benchmarks"},
    "side.dashboard": {"en": "Dashboard", "de": "Dashboard"},
    "side.how": {"en": "How it answers", "de": "Wie es antwortet"},
    "side.bookmark": {"en": "Bookmark", "de": "Merken"},
    "side.unbookmark": {"en": "Remove bookmark", "de": "Nicht mehr merken"},
    "side.rename": {"en": "Rename", "de": "Umbenennen"},
    "side.save_name": {"en": "Save name", "de": "Namen speichern"},
    "side.delete": {"en": "Delete", "de": "Löschen"},
    "side.signed_in": {"en": "Signed in as {name}", "de": "Angemeldet als {name}"},
    "side.sign_out": {"en": "Sign out", "de": "Abmelden"},
    "side.saved_here": {"en": "Saved on this computer.", "de": "Auf diesem Computer gespeichert."},
    "side.settings": {"en": "Settings", "de": "Einstellungen"},
    "group.Bookmarked": {"en": "Bookmarked", "de": "Gemerkt"},
    "group.Today": {"en": "Today", "de": "Heute"},
    "group.Yesterday": {"en": "Yesterday", "de": "Gestern"},
    "group.Previous 7 days": {"en": "Previous 7 days", "de": "Letzte 7 Tage"},
    "group.Older": {"en": "Older", "de": "Älter"},
    # Settings
    "set.title": {"en": "Settings", "de": "Einstellungen"},
    "set.language": {"en": "Language", "de": "Sprache"},
    "set.language_help": {"en": "Answers, buttons and labels use this language. Place names stay as they are. "
                                "Benchmarks, Dashboard, How it answers and the trip pages are in English.",
                          "de": "Antworten, Schaltflächen und Beschriftungen in dieser Sprache. Ortsnamen bleiben "
                                "unverändert. Benchmarks, Dashboard, Wie es antwortet und die Reiseseiten sind auf "
                                "Englisch."},
    "set.checks": {"en": "How each message is checked", "de": "Wie jede Nachricht geprüft wird"},
    "set.checks_note": {"en": "Before the answer, so unsafe or off-limits input never reaches the model. These are "
                              "rules, not a model, so they can't be switched.",
                        "de": "Vor der Antwort, damit unsichere oder unzulässige Eingaben das Modell nie erreichen. "
                              "Das sind Regeln, kein Modell, daher lassen sie sich nicht abschalten."},
    "set.guard": {"en": "Input guard", "de": "Eingabeprüfung"},
    "set.guard_tags": {"en": "rules · always on", "de": "Regeln · immer an"},
    "set.guard_text": {"en": "Every message is checked before the model sees it: length, control characters and "
                             "prompt-injection patterns. Refused messages are counted on the dashboard.",
                       "de": "Jede Nachricht wird geprüft, bevor das Modell sie sieht: Länge, Steuerzeichen und "
                             "Prompt-Injection-Muster. Abgelehnte Nachrichten werden im Dashboard gezählt."},
    "set.screening": {"en": "Tool result screening", "de": "Prüfung der Tool-Ergebnisse"},
    "set.screening_text": {"en": "Text from outside sources (listing names, place descriptions) is screened for "
                                 "injected instructions, links are kept only if they're http(s), and long text is "
                                 "trimmed.",
                           "de": "Text aus externen Quellen (Inseratsnamen, Ortsbeschreibungen) wird auf "
                                 "eingeschleuste Anweisungen geprüft, nur http(s)-Links bleiben erhalten und langer "
                                 "Text wird gekürzt."},
    "set.model": {"en": "Model that writes the answers", "de": "Modell für die Antworten"},
    "set.model_note": {"en": "It reads your question, calls the tools, and also writes the knowledge-base search "
                             "queries. Prices are USD per million tokens (input / output).",
                       "de": "Es liest deine Frage, ruft die Tools auf und schreibt auch die Suchanfragen für die "
                             "Wissensdatenbank. Preise in USD pro Million Tokens (Eingabe / Ausgabe)."},
    "set.tag.cloud": {"en": "cloud", "de": "Cloud"},
    "set.tag.tested": {"en": "tested", "de": "getestet"},
    "set.tag.default": {"en": "default", "de": "Standard"},
    "set.model_warning": {"en": "TripMate was developed and evaluated with {model}, so its rules for tools, costs and "
                                "answer formats were tuned on it. Another model can do worse here: it may skip a "
                                "tool, cost a plan by itself or follow the answer formats less closely.",
                          "de": "TripMate wurde mit {model} entwickelt und bewertet, daher sind die Regeln für "
                                "Tools, Kosten und Antwortformate darauf abgestimmt. Ein anderes Modell kann hier "
                                "schlechter sein: Es überspringt vielleicht ein Tool, berechnet einen Plan selbst "
                                "oder hält sich weniger an die Antwortformate."},
    "set.model_prices": {"en": "Prices, totals and the plan checks always come from the tools, whichever model you "
                               "choose.",
                         "de": "Preise, Summen und die Planprüfungen kommen immer von den Tools, egal welches "
                               "Modell du wählst."},
    "set.currency": {"en": "Currency", "de": "Währung"},
    "set.currency_help": {"en": "Budgets, trip totals and listing prices use this currency, at today's rate.",
                          "de": "Budgets, Reisesummen und Inseratspreise in dieser Währung, zum heutigen Kurs."},
    "set.live": {"en": "Live searches", "de": "Live-Suchen"},
    "set.live_note": {"en": "Allowed per chat, so one chat can't use up the monthly quota. This chat: {used}. "
                            "Repeated searches come from the cache for free; a new chat starts again from zero.",
                      "de": "Pro Chat begrenzt, damit ein Chat nicht das Monatskontingent aufbraucht. Dieser Chat: "
                            "{used}. Wiederholte Suchen kommen kostenlos aus dem Cache; ein neuer Chat beginnt "
                            "wieder bei null."},
    "set.of": {"en": "of", "de": "von"},
    "set.history": {"en": "Chat history", "de": "Chatverlauf"},
    "set.history_note": {"en": "Chats are saved on this computer in .history/chats.sqlite3 (not in git).",
                         "de": "Chats werden auf diesem Computer in .history/chats.sqlite3 gespeichert (nicht in "
                               "git)."},
    "set.export_md": {"en": "Export chat (Markdown)", "de": "Chat exportieren (Markdown)"},
    "set.export_json": {"en": "Export chat (JSON)", "de": "Chat exportieren (JSON)"},
    "set.confirm_delete": {"en": "Yes, delete every saved chat and the dashboard log",
                           "de": "Ja, alle gespeicherten Chats und das Dashboard-Protokoll löschen"},
    "set.delete_all": {"en": "Delete all history", "de": "Gesamten Verlauf löschen"},
    "set.kb": {"en": "Knowledge base", "de": "Wissensdatenbank"},
    "set.kb_note": {"en": "Re-embeds every place from data/world/. Only needed after changing the data by hand; "
                          "the app adds new places by itself at startup.",
                    "de": "Bettet jeden Ort aus data/world/ neu ein. Nur nötig, wenn die Daten von Hand geändert "
                          "wurden; neue Orte fügt die App beim Start selbst hinzu."},
    "set.kb_rebuild": {"en": "Rebuild knowledge base", "de": "Wissensdatenbank neu aufbauen"},
    "set.kb_progress": {"en": "Re-indexing places...", "de": "Orte werden neu indexiert..."},
    "set.kb_indexed": {"en": "Indexed {done} of {total} places", "de": "{done} von {total} Orten indexiert"},
    "set.kb_done": {"en": "Indexed {count} places.", "de": "{count} Orte indexiert."},
    "set.applies": {"en": "Changes apply straight away.", "de": "Änderungen gelten sofort."},
    "set.done": {"en": "Done", "de": "Fertig"},
    # Sign-in, sign-up and password reset (frontend/pages/sign_in.py)
    "auth.name": {"en": "Username or email address", "de": "Benutzername oder E-Mail-Adresse"},
    "auth.password": {"en": "Password", "de": "Passwort"},
    "auth.remember": {"en": "Remember me", "de": "Angemeldet bleiben"},
    "auth.remember_help": {"en": "Stay signed in on this browser for 30 days.",
                           "de": "30 Tage lang in diesem Browser angemeldet bleiben."},
    "auth.forgot": {"en": "Forgot your password?", "de": "Passwort vergessen?"},
    "auth.sign_in": {"en": "Sign in", "de": "Anmelden"},
    "auth.or": {"en": "or", "de": "oder"},
    "auth.google": {"en": "Continue with Google", "de": "Weiter mit Google"},
    "auth.no_account": {"en": "Don't have an account?", "de": "Noch kein Konto?"},
    "auth.sign_up": {"en": "Sign up", "de": "Registrieren"},
    "auth.private": {"en": "Your chats, trips and documents are private to your account.",
                     "de": "Deine Chats, Reisen und Dokumente sind nur für dein Konto sichtbar."},
    "auth.sign_up_title": {"en": "Create your account", "de": "Konto erstellen"},
    "auth.username": {"en": "Username", "de": "Benutzername"},
    "auth.username_help": {"en": "3 to 30 letters, digits, dots, dashes or underscores.",
                           "de": "3 bis 30 Buchstaben, Ziffern, Punkte, Binde- oder Unterstriche."},
    "auth.email": {"en": "Email address", "de": "E-Mail-Adresse"},
    "auth.email_example": {"en": "you@example.com", "de": "du@beispiel.de"},
    "auth.password_help": {"en": "At least 10 characters.", "de": "Mindestens 10 Zeichen."},
    "auth.repeat": {"en": "Repeat password", "de": "Passwort wiederholen"},
    "auth.create": {"en": "Create account", "de": "Konto erstellen"},
    "auth.have_account": {"en": "Already have an account?", "de": "Schon ein Konto?"},
    "auth.check_inbox": {"en": "Almost done: we've sent a link to {email}. Open it to confirm your email, "
                               "then sign in.",
                         "de": "Fast fertig: Wir haben einen Link an {email} geschickt. Öffne ihn, um deine "
                               "E-Mail zu bestätigen, und melde dich dann an."},
    "auth.waiting_owner": {"en": "Your account is created. The TripMate owner confirms new accounts; you can "
                                 "sign in once yours is confirmed.",
                           "de": "Dein Konto ist erstellt. Der TripMate-Betreiber bestätigt neue Konten; du "
                                 "kannst dich anmelden, sobald deins bestätigt ist."},
    "auth.confirmed": {"en": "Your email is confirmed. You can sign in now.",
                       "de": "Deine E-Mail ist bestätigt. Du kannst dich jetzt anmelden."},
    "auth.forgot_title": {"en": "Reset your password", "de": "Passwort zurücksetzen"},
    "auth.forgot_note": {"en": "Enter your account's email address and we'll send you a link to choose a new "
                               "password.",
                         "de": "Gib die E-Mail-Adresse deines Kontos ein, und wir schicken dir einen Link, um ein "
                               "neues Passwort zu wählen."},
    "auth.send_link": {"en": "Send reset link", "de": "Link senden"},
    "auth.link_sent": {"en": "If an account has this email, a link is on its way. It works once, for 30 minutes.",
                       "de": "Wenn ein Konto diese E-Mail hat, ist ein Link unterwegs. Er funktioniert einmal, "
                             "30 Minuten lang."},
    "auth.ask_owner": {"en": "Password resets by email aren't set up yet. Please ask the TripMate owner to "
                             "help you.",
                       "de": "Passwort-Zurücksetzen per E-Mail ist noch nicht eingerichtet. Bitte wende dich an "
                             "den TripMate-Betreiber."},
    "auth.back": {"en": "Back to sign in", "de": "Zurück zur Anmeldung"},
    "auth.new_title": {"en": "Choose a new password", "de": "Wähle ein neues Passwort"},
    "auth.new_password": {"en": "New password", "de": "Neues Passwort"},
    "auth.save_password": {"en": "Save new password", "de": "Neues Passwort speichern"},
    "auth.password_saved": {"en": "Your new password is saved. You can sign in with it now.",
                            "de": "Dein neues Passwort ist gespeichert. Du kannst dich jetzt damit anmelden."},
    "auth.error.wrong": {"en": "Wrong username, email or password.",
                         "de": "Falscher Benutzername, falsche E-Mail oder falsches Passwort."},
    "auth.error.locked": {"en": "Too many wrong tries. Please wait {minutes} minutes and try again.",
                          "de": "Zu viele falsche Versuche. Bitte warte {minutes} Minuten und versuch es "
                                "noch einmal."},
    "auth.error.not_confirmed": {"en": "Please confirm your email first: open the link we sent you.",
                                 "de": "Bitte bestätige zuerst deine E-Mail: Öffne den Link, den wir dir "
                                       "geschickt haben."},
    "auth.error.not_confirmed_owner": {"en": "Your account is waiting for the TripMate owner to confirm it.",
                                       "de": "Dein Konto wartet darauf, dass der TripMate-Betreiber es "
                                             "bestätigt."},
    "auth.error.username_invalid": {"en": "Usernames have 3 to 30 letters, digits, dots, dashes or underscores.",
                                    "de": "Benutzernamen haben 3 bis 30 Buchstaben, Ziffern, Punkte, Binde- "
                                          "oder Unterstriche."},
    "auth.error.email_invalid": {"en": "Please enter a valid email address.",
                                 "de": "Bitte gib eine gültige E-Mail-Adresse ein."},
    "auth.error.password_short": {"en": "The password needs at least 10 characters.",
                                  "de": "Das Passwort braucht mindestens 10 Zeichen."},
    "auth.error.password_long": {"en": "The password can have at most 200 characters.",
                                 "de": "Das Passwort darf höchstens 200 Zeichen haben."},
    "auth.error.password_mismatch": {"en": "The two passwords don't match.",
                                     "de": "Die beiden Passwörter stimmen nicht überein."},
    "auth.error.account_taken": {"en": "That username or email already has an account.",
                                 "de": "Für diesen Benutzernamen oder diese E-Mail gibt es schon ein Konto."},
    "auth.error.link_expired": {"en": "This link has expired or was already used. Ask for a new one.",
                                "de": "Dieser Link ist abgelaufen oder wurde schon benutzt. Fordere einen "
                                      "neuen an."},
    "set.accounts": {"en": "Accounts waiting for confirmation", "de": "Konten, die auf Bestätigung warten"},
    "set.accounts_note": {"en": "Only you see this, as the owner. Confirm an account when you know the person "
                                "owns its email address: it will see that email's chats and trips.",
                          "de": "Nur du siehst das, als Betreiber. Bestätige ein Konto, wenn du weißt, dass "
                                "der Person die E-Mail-Adresse gehört: Sie sieht die Chats und Reisen dieser "
                                "E-Mail."},
    "set.accounts_none": {"en": "No accounts are waiting.", "de": "Keine Konten warten."},
    "set.confirm": {"en": "Confirm", "de": "Bestätigen"},
    # Progress messages while the agent works (backend/agent/agent.py sends them in English)
    "step.Reading your request...": {"en": "Reading your request...", "de": "Lese deine Anfrage..."},
    "step.Costing the plan...": {"en": "Costing the plan...", "de": "Berechne die Kosten..."},
    "step.Writing the answer...": {"en": "Writing the answer...", "de": "Schreibe die Antwort..."},
    "step.Searching live flights...": {"en": "Searching live flights...", "de": "Suche Live-Flüge..."},
    "step.Looking for places to stay...": {"en": "Looking for places to stay...", "de": "Suche Unterkünfte..."},
    "step.Finding restaurants...": {"en": "Finding restaurants...", "de": "Suche Restaurants..."},
    "step.Searching places to see...": {"en": "Searching places to see...", "de": "Suche Sehenswürdigkeiten..."},
    "step.Checking public transport and driving routes...": {
        "en": "Checking public transport and driving routes...", "de": "Prüfe ÖPNV- und Autorouten..."},
    "step.Checking the plan...": {"en": "Checking the plan...", "de": "Prüfe den Plan..."},
    "step.working": {"en": "Working on your answer (step {step})...", "de": "Arbeite an deiner Antwort (Schritt {step})..."},
}

# Example questions on an empty chat, by language. Plan examples get dates from today (trip_form.py).
EXPLORE_EXAMPLES = {
    "en": ["Museums for kids in Chicago.", "Sushi restaurants in Tokyo rated 4.5 or more.",
           "Which areas of Lisbon are nice to stay in, and what is there to see?",
           "How do I get from Fiumicino Airport to the Colosseum?"],
    "de": ["Museen für Kinder in Chicago.", "Sushi-Restaurants in Tokio mit 4,5 Sternen oder mehr.",
           "Welche Viertel in Lissabon sind schön zum Wohnen, und was gibt es dort zu sehen?",
           "Wie komme ich vom Flughafen Fiumicino zum Kolosseum?"],
}


def language() -> str:
    """The language chosen in Settings (English until one is chosen)."""
    chosen = st.session_state.get("language", DEFAULT_LANGUAGE)
    return chosen if chosen in LANGUAGES else DEFAULT_LANGUAGE


def t(key: str, **values) -> str:
    """The text for key in the chosen language, with {placeholders} filled in."""
    text = TEXTS[key][language()]
    return text.format(**values) if values else text


def step_text(text: str) -> str:
    """A progress message from the agent, in the chosen language (unknown ones stay as they are)."""
    if f"step.{text}" in TEXTS:
        return t(f"step.{text}")
    if match := re.fullmatch(r"Working on your answer \(step (\d+)\)\.\.\.", text):
        return t("step.working", step=match.group(1))
    return text
