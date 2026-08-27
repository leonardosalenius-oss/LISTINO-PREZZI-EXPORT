"""
Listino Ortofrutta — app Streamlit collegata a un Google Apps Script
(niente Google Cloud Console, niente carta di credito).

Vista cliente: multilingua (IT/EN/FR/ES/PL/EL/PT), sola lettura.
Vista fornitore: protetta da PIN, permette di modificare prezzi,
disponibilità, categoria e unità di misura di ogni prodotto.
"""

import streamlit as st
import requests
from datetime import date
import pandas as pd
import json

st.set_page_config(page_title="Listino Ortofrutta", page_icon="📦", layout="centered")

APPS_SCRIPT_URL = st.secrets["APPS_SCRIPT_URL"]
API_KEY = st.secrets["API_KEY"]
SUPPLIER_PIN = st.secrets.get("SUPPLIER_PIN", "1234")

REQUEST_TIMEOUT = 20


# ---------------------------------------------------------------------------
# Chiamate all'API (Google Apps Script)
# ---------------------------------------------------------------------------
def api_get(action):
    try:
        resp = requests.get(APPS_SCRIPT_URL, params={"action": action, "key": API_KEY}, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, dict) and data.get("error"):
            st.error(f"Errore dal backend: {data['error']}")
            return []
        return data
    except requests.exceptions.RequestException as e:
        st.error(f"Impossibile contattare il listino (Apps Script). Dettagli: {e}")
        return []


def api_post(payload):
    payload = {**payload, "key": API_KEY}
    try:
        resp = requests.post(APPS_SCRIPT_URL, json=payload, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, dict) and data.get("error"):
            st.error(f"Errore dal backend: {data['error']}")
            return None
        return data
    except requests.exceptions.RequestException as e:
        st.error(f"Impossibile salvare (Apps Script). Dettagli: {e}")
        return None


# ---------------------------------------------------------------------------
# Traduzioni interfaccia e unità di misura
# ---------------------------------------------------------------------------
LANGUAGES = [("it", "IT"), ("en", "EN"), ("fr", "FR"), ("es", "ES"), ("pl", "PL"), ("el", "EL"), ("pt", "PT")]

UI = {
    "it": {"title": "Listino Ortofrutta", "updated": "Aggiornato al", "unavailable": "Non disponibile", "footer": "Prezzi indicativi, franco Volla (NA), salvo conferma disponibilità."},
    "en": {"title": "Fresh Produce Price List", "updated": "Updated on", "unavailable": "Not available", "footer": "Indicative prices, ex-works Volla (Naples, Italy), subject to availability confirmation."},
    "fr": {"title": "Liste de prix Fruits & Légumes", "updated": "Mis à jour le", "unavailable": "Indisponible", "footer": "Prix indicatifs, départ Volla (Naples, Italie), sous réserve de disponibilité."},
    "es": {"title": "Lista de precios Frutas y Verduras", "updated": "Actualizado el", "unavailable": "No disponible", "footer": "Precios indicativos, salida Volla (Nápoles, Italia), sujeto a confirmación de disponibilidad."},
    "pl": {"title": "Cennik Owoców i Warzyw", "updated": "Zaktualizowano", "unavailable": "Niedostępne", "footer": "Ceny orientacyjne, loco Volla (Neapol, Włochy), z zastrzeżeniem dostępności."},
    "el": {"title": "Τιμοκατάλογος Οπωροκηπευτικών", "updated": "Ενημερώθηκε στις", "unavailable": "Μη διαθέσιμο", "footer": "Ενδεικτικές τιμές, εκ Volla (Νάπολη, Ιταλία), με την επιφύλαξη διαθεσιμότητας."},
    "pt": {"title": "Lista de Preços Hortofrutícolas", "updated": "Atualizado em", "unavailable": "Indisponível", "footer": "Preços indicativos, saída de Volla (Nápoles, Itália), sujeitos a confirmação de disponibilidade."},
}

UNIT_LABELS = {
    "kg": {"it": "kg", "en": "kg", "fr": "kg", "es": "kg", "pl": "kg", "el": "κιλό", "pt": "kg"},
    "g": {"it": "g", "en": "g", "fr": "g", "es": "g", "pl": "g", "el": "γρ", "pt": "g"},
    "cassa": {"it": "cassa", "en": "box", "fr": "caisse", "es": "caja", "pl": "skrzynka", "el": "κιβώτιο", "pt": "caixa"},
    "testa": {"it": "testa", "en": "head", "fr": "pièce", "es": "unidad", "pl": "sztuka", "el": "τεμάχιο", "pt": "unidade"},
}
UNITS = ["kg", "g", "cassa", "testa"]


def unit_label(u, lang):
    return UNIT_LABELS.get(u, {}).get(lang, u)


def cat_label(categoria, cat_trad_map, lang):
    if lang == "it":
        return categoria
    row = cat_trad_map.get(categoria)
    return (row.get(lang) if row else None) or categoria


def name_label(prodotto, lang):
    if lang == "it":
        return prodotto["nome"]
    trad = prodotto.get("traduzioni") or {}
    return trad.get(lang) or prodotto["nome"]


def calc_prezzo_kg(prezzo_base, unita_base, peso_unitario_kg):
    if unita_base == "kg":
        return prezzo_base
    if unita_base == "g":
        return prezzo_base * 1000
    if unita_base in ("cassa", "testa"):
        if peso_unitario_kg and peso_unitario_kg > 0:
            return prezzo_base / peso_unitario_kg
        return None
    return None


# ---------------------------------------------------------------------------
# Accesso ai dati (con piccola cache per non consumare inutilmente le chiamate)
# ---------------------------------------------------------------------------
def _parse_bool(v):
    return str(v).strip().upper() == "TRUE"


def _parse_float_or_none(v):
    if v is None or str(v).strip() == "":
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


@st.cache_data(ttl=15)
def load_products():
    raw = api_get("products")
    products = []
    for r in raw:
        if not r.get("id"):
            continue
        try:
            traduzioni = json.loads(r.get("traduzioni_json") or "{}")
        except json.JSONDecodeError:
            traduzioni = {}
        products.append({
            "id": r["id"],
            "categoria": r["categoria"],
            "nome": r["nome"],
            "formato": r.get("formato", ""),
            "prezzo_base": float(r.get("prezzo_base") or 0),
            "unita_base": r.get("unita_base") or "kg",
            "peso_unitario_kg": _parse_float_or_none(r.get("peso_unitario_kg")),
            "disponibile": _parse_bool(r.get("disponibile")),
            "traduzioni": traduzioni,
            "ordine": int(float(r.get("ordine") or 0)),
        })
    products.sort(key=lambda p: p["ordine"])
    return products


@st.cache_data(ttl=60)
def load_categorie_trad():
    raw = api_get("categories")
    return {r["categoria"]: r for r in raw if r.get("categoria")}


@st.cache_data(ttl=15)
def load_storico_recente():
    raw = api_get("history")
    by_product = {}
    for r in raw:
        pid = r.get("prodotto_id")
        if not pid:
            continue
        perkg = _parse_float_or_none(r.get("prezzo_per_kg"))
        by_product.setdefault(pid, []).append({"data": r.get("data"), "prezzo_per_kg": perkg})
    for pid in by_product:
        by_product[pid].sort(key=lambda x: str(x["data"]), reverse=True)
    return by_product


def trend_symbol(storico_prodotto):
    if not storico_prodotto or len(storico_prodotto) < 2:
        return ""
    ultimo, precedente = storico_prodotto[0]["prezzo_per_kg"], storico_prodotto[1]["prezzo_per_kg"]
    if ultimo is None or precedente is None or abs(ultimo - precedente) < 0.001:
        return "→"
    return "↑" if ultimo > precedente else "↓"


def invalidate_cache():
    load_products.clear()
    load_storico_recente.clear()


# ---------------------------------------------------------------------------
# Scrittura
# ---------------------------------------------------------------------------
def save_product(product_id, updates, old_product):
    merged = {**old_product, **updates}

    # Il backend salva i valori come li mandiamo: prepariamo il formato giusto
    api_updates = dict(updates)
    if "disponibile" in api_updates:
        api_updates["disponibile"] = "TRUE" if api_updates["disponibile"] else "FALSE"
    if "peso_unitario_kg" in api_updates and api_updates["peso_unitario_kg"] is None:
        api_updates["peso_unitario_kg"] = ""

    result = api_post({"action": "update_product", "id": product_id, "updates": api_updates})
    if result is None:
        return False

    price_changed = (
        updates.get("prezzo_base", old_product["prezzo_base"]) != old_product["prezzo_base"]
        or updates.get("unita_base", old_product["unita_base"]) != old_product["unita_base"]
        or updates.get("peso_unitario_kg", old_product["peso_unitario_kg"]) != old_product["peso_unitario_kg"]
    )
    if price_changed:
        perkg = calc_prezzo_kg(merged["prezzo_base"], merged["unita_base"], merged["peso_unitario_kg"])
        api_post({
            "action": "add_history",
            "entry": {
                "prodotto_id": product_id,
                "data": date.today().isoformat(),
                "prezzo_base": merged["prezzo_base"],
                "unita_base": merged["unita_base"],
                "peso_unitario_kg": merged["peso_unitario_kg"],
                "prezzo_per_kg": perkg,
            },
        })
    return True


def create_product(nome, categoria, formato):
    return api_post({"action": "create_product", "nome": nome, "categoria": categoria, "formato": formato})


def delete_product(product_id):
    return api_post({"action": "delete_product", "id": product_id})


# ---------------------------------------------------------------------------
# Stile
# ---------------------------------------------------------------------------
st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Oswald:wght@500;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap');
    .stApp { background-color: #182620; }
    .product-card {
        background: #F5F0E1; border-radius: 10px; padding: 12px 16px;
        margin-bottom: 8px; display: flex; justify-content: space-between; align-items: center;
    }
    .product-card.unavailable { background: #E7E0CC; opacity: 0.65; }
    .product-name { font-family: 'Oswald', sans-serif; font-weight: 600; text-transform: uppercase;
        letter-spacing: 0.03em; font-size: 0.92rem; color: #20291F; }
    .product-format { font-size: 0.78rem; color: #5B6B5D; margin-top: 2px; }
    .product-price { font-family: 'IBM Plex Mono', monospace; font-weight: 700; font-size: 1.05rem; color: #20291F; }
    .product-unit { font-size: 0.75rem; color: #5B6B5D; }
    .product-conv { font-family: 'IBM Plex Mono', monospace; font-size: 0.72rem; color: #D3A22C; }
    .cat-header { font-family: 'Oswald', sans-serif; text-transform: uppercase; letter-spacing: 0.08em;
        font-size: 0.8rem; color: #F5F0E1; margin: 20px 0 8px 0; border-bottom: 1px solid #3A4A3D; padding-bottom: 4px; }
    .app-title { font-family: 'Oswald', sans-serif; color: #F5F0E1; text-transform: uppercase; }
    .footer-note { color: #5B6B5D; font-family: 'IBM Plex Mono', monospace; font-size: 0.72rem; text-align: center; margin-top: 24px; }
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Stato sessione
# ---------------------------------------------------------------------------
if "supplier_mode" not in st.session_state:
    st.session_state.supplier_mode = False
if "lang" not in st.session_state:
    st.session_state.lang = "it"

with st.sidebar:
    st.markdown("### 🔒 Accesso fornitore")
    if not st.session_state.supplier_mode:
        pin_input = st.text_input("PIN", type="password", key="pin_input")
        if st.button("Entra"):
            if pin_input == SUPPLIER_PIN:
                st.session_state.supplier_mode = True
                st.rerun()
            else:
                st.error("PIN errato.")
    else:
        st.success("Modalità fornitore attiva")
        if st.button("Esci dalla modalità fornitore"):
            st.session_state.supplier_mode = False
            st.rerun()


# ---------------------------------------------------------------------------
# Vista CLIENTE
# ---------------------------------------------------------------------------
def render_customer_view():
    lang = st.session_state.lang
    t = UI[lang]

    st.markdown(f"<h1 class='app-title'>📦 {t['title']}</h1>", unsafe_allow_html=True)

    cols = st.columns(len(LANGUAGES))
    for i, (code, label) in enumerate(LANGUAGES):
        with cols[i]:
            if st.button(label, key=f"lang_{code}", type=("primary" if lang == code else "secondary"), use_container_width=True):
                st.session_state.lang = code
                st.rerun()

    products = load_products()
    cat_trad = load_categorie_trad()
    storico = load_storico_recente()

    if not products:
        st.info("Nessun prodotto nel listino al momento (o problema di connessione al backend — controlla la sidebar per eventuali errori).")
        return

    categorie = {}
    for p in products:
        categorie.setdefault(p["categoria"], []).append(p)

    for categoria, items in categorie.items():
        st.markdown(f"<div class='cat-header'>{cat_label(categoria, cat_trad, lang)}</div>", unsafe_allow_html=True)
        for p in items:
            nome = name_label(p, lang)
            disponibile = p["disponibile"]
            css_class = "product-card" if disponibile else "product-card unavailable"

            if disponibile:
                perkg = calc_prezzo_kg(p["prezzo_base"], p["unita_base"], p["peso_unitario_kg"])
                arrow = trend_symbol(storico.get(p["id"], []))
                conv_html = ""
                if p["unita_base"] != "kg" and perkg is not None:
                    conv_html = f"<div class='product-conv'>≈ {perkg:.2f} €/kg</div>"
                right_html = (
                    f"<div style='text-align:right'>"
                    f"<span class='product-price'>{arrow} {p['prezzo_base']:.2f}</span> "
                    f"<span class='product-unit'>€/{unit_label(p['unita_base'], lang)}</span>"
                    f"{conv_html}</div>"
                )
            else:
                right_html = f"<div style='color:#A6412E; font-size:0.75rem; font-weight:700; text-transform:uppercase;'>{t['unavailable']}</div>"

            st.markdown(
                f"<div class='{css_class}'>"
                f"<div><div class='product-name'>{nome}</div><div class='product-format'>{p['formato'] or ''}</div></div>"
                f"{right_html}</div>",
                unsafe_allow_html=True,
            )

    st.markdown(f"<div class='footer-note'>{t['footer']}</div>", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Vista FORNITORE
# ---------------------------------------------------------------------------
def render_supplier_view():
    st.markdown("<h1 class='app-title'>🔧 Modalità fornitore</h1>", unsafe_allow_html=True)
    st.caption("Le modifiche vengono salvate direttamente sul Google Sheet, tramite Apps Script.")

    products = load_products()
    all_categories = sorted(set(p["categoria"] for p in products))

    with st.expander("➕ Aggiungi nuovo prodotto"):
        with st.form("nuovo_prodotto"):
            c1, c2 = st.columns(2)
            nome = c1.text_input("Nome prodotto")
            categoria = c2.selectbox("Categoria", all_categories + ["+ Nuova categoria..."])
            if categoria == "+ Nuova categoria...":
                categoria = st.text_input("Nome nuova categoria")
            formato = st.text_input("Formato (testo libero, es. 'cassa 8pz')")
            submitted = st.form_submit_button("Crea prodotto")
            if submitted and nome and categoria:
                create_product(nome, categoria, formato)
                invalidate_cache()
                st.success(f"Prodotto '{nome}' creato.")
                st.rerun()

    st.divider()

    categorie = {}
    for p in products:
        categorie.setdefault(p["categoria"], []).append(p)

    for categoria, items in categorie.items():
        st.markdown(f"<div class='cat-header' style='color:#F5F0E1'>{categoria}</div>", unsafe_allow_html=True)
        for p in items:
            with st.expander(f"{p['nome']}  —  {p['prezzo_base']:.2f} €/{unit_label(p['unita_base'],'it')}"
                              f"{'' if p['disponibile'] else '  [NON DISPONIBILE]'}"):
                with st.form(f"edit_{p['id']}"):
                    c1, c2 = st.columns(2)
                    nome = c1.text_input("Nome", value=p["nome"], key=f"nome_{p['id']}")
                    cat_options = all_categories + ["+ Nuova categoria..."]
                    cat_idx = cat_options.index(p["categoria"]) if p["categoria"] in cat_options else 0
                    new_cat = c2.selectbox("Categoria", cat_options, index=cat_idx, key=f"cat_{p['id']}")
                    if new_cat == "+ Nuova categoria...":
                        new_cat = st.text_input("Nome nuova categoria", key=f"newcat_{p['id']}")

                    formato = st.text_input("Formato (testo libero)", value=p["formato"] or "", key=f"formato_{p['id']}")

                    c3, c4, c5 = st.columns(3)
                    prezzo = c3.number_input("Prezzo", value=float(p["prezzo_base"]), step=0.05, format="%.2f", key=f"prezzo_{p['id']}")
                    unita = c4.selectbox("Unità", UNITS, index=UNITS.index(p["unita_base"]), key=f"unita_{p['id']}")
                    peso = None
                    if unita in ("cassa", "testa"):
                        peso = c5.number_input(
                            f"Peso {unita} (kg)", value=float(p["peso_unitario_kg"] or 0), step=0.1, format="%.2f",
                            key=f"peso_{p['id']}"
                        )
                    disponibile = st.checkbox("Disponibile", value=p["disponibile"], key=f"disp_{p['id']}")

                    perkg_preview = calc_prezzo_kg(prezzo, unita, peso)
                    if unita in ("cassa", "testa"):
                        if perkg_preview is not None:
                            st.caption(f"≈ {perkg_preview:.2f} €/kg (calcolo automatico)")
                        else:
                            st.caption("Inserisci il peso per calcolare il prezzo al kg")

                    save = st.form_submit_button("💾 Salva")
                    delete = st.form_submit_button("🗑️ Elimina prodotto")

                    if save:
                        updates = {
                            "nome": nome, "categoria": new_cat, "formato": formato,
                            "prezzo_base": prezzo, "unita_base": unita,
                            "peso_unitario_kg": peso if unita in ("cassa", "testa") else None,
                            "disponibile": disponibile,
                        }
                        if save_product(p["id"], updates, p):
                            invalidate_cache()
                            st.success("Salvato.")
                            st.rerun()

                    if delete:
                        delete_product(p["id"])
                        invalidate_cache()
                        st.warning(f"Prodotto '{p['nome']}' eliminato.")
                        st.rerun()

                # Storico prezzi (sola lettura)
                storico_prodotto = load_storico_recente().get(p["id"], [])
                if storico_prodotto:
                    df = pd.DataFrame(storico_prodotto[:10])
                    df.columns = ["Data", "€/kg"]
                    st.caption("Storico recente")
                    st.dataframe(df, hide_index=True, use_container_width=True)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if st.session_state.supplier_mode:
    render_supplier_view()
else:
    render_customer_view()
