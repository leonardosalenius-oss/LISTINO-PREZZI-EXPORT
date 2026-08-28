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
import urllib.parse
import base64
from pathlib import Path

st.set_page_config(page_title="Listino Ortofrutta", page_icon="📦", layout="centered")

APPS_SCRIPT_URL = st.secrets["APPS_SCRIPT_URL"]
API_KEY = st.secrets["API_KEY"]
SUPPLIER_PIN = st.secrets.get("SUPPLIER_PIN", "1234")
ORDER_WHATSAPP_NUMBERS = st.secrets.get("ORDER_WHATSAPP_NUMBERS", [])  # lista, es. ["393331234567", "393339876543"]
ORDER_WHATSAPP_LABELS = st.secrets.get("ORDER_WHATSAPP_LABELS", [])  # etichette opzionali, stesso ordine dei numeri
ORDER_EMAIL = st.secrets.get("ORDER_EMAIL", "")

ASSETS_DIR = Path(__file__).parent / "assets"


@st.cache_data
def load_logo_b64(filename):
    path = ASSETS_DIR / filename
    if not path.exists():
        return None
    return base64.b64encode(path.read_bytes()).decode()


LOGOS = [
    (load_logo_b64("logo_antonio_processed.png"), "png"),
    (load_logo_b64("logo_hex_processed.png"), "png"),
    (load_logo_b64("logo_soria_coop_processed.png"), "png"),
]

# Loghi certificazioni: aggiungi qui appena disponibili i file (stessa cartella assets/)
CERT_LOGOS = [
    (load_logo_b64("cert_iso9001_processed.png"), "png", "ISO 9001"),
    (load_logo_b64("cert_globalgap_processed.png"), "png", "Global G.A.P."),
    (load_logo_b64("cert_ifsfood_processed.png"), "png", "IFS Food"),
]

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
    "it": {"title": "Listino Prezzi Gruppo Soria", "updated": "Aggiornato al", "unavailable": "Non disponibile", "footer": "Prezzi indicativi, franco Volla (NA), salvo conferma disponibilità.",
           "order_title": "Il tuo ordine", "qty": "Quantità", "no_items": "Seleziona le quantità dei prodotti che ti interessano qui sopra: appariranno qui.",
           "reference": "Il tuo nome / azienda (facoltativo)", "send_whatsapp": "📲 Invia ordine via WhatsApp", "send_email": "✉️ Invia ordine via Email",
           "order_header": "Nuovo ordine dal listino", "order_subject": "Nuovo ordine", "not_configured": "Contatti per l'ordine non ancora configurati.", "total": "Totale", "restricted_area": "Area riservata fornitori", "reference_label": "Cliente", "reference_placeholder": "non specificato", "package_of": "confezione da", "packages_unit": "confezioni"},
    "en": {"title": "Gruppo Soria — Fresh Produce Price List", "updated": "Updated on", "unavailable": "Not available", "footer": "Indicative prices, ex-works Volla (Naples, Italy), subject to availability confirmation.",
           "order_title": "Your order", "qty": "Quantity", "no_items": "Select quantities for the products you need above: they'll appear here.",
           "reference": "Your name / company (optional)", "send_whatsapp": "📲 Send order via WhatsApp", "send_email": "✉️ Send order via Email",
           "order_header": "New order from the price list", "order_subject": "New order", "not_configured": "Order contact details not configured yet.", "total": "Total", "restricted_area": "Supplier restricted area", "reference_label": "Customer", "reference_placeholder": "not specified", "package_of": "package of", "packages_unit": "packages"},
    "fr": {"title": "Gruppo Soria — Liste de prix Fruits & Légumes", "updated": "Mis à jour le", "unavailable": "Indisponible", "footer": "Prix indicatifs, départ Volla (Naples, Italie), sous réserve de disponibilité.",
           "order_title": "Votre commande", "qty": "Quantité", "no_items": "Sélectionnez les quantités des produits souhaités ci-dessus : elles apparaîtront ici.",
           "reference": "Votre nom / entreprise (facultatif)", "send_whatsapp": "📲 Envoyer la commande via WhatsApp", "send_email": "✉️ Envoyer la commande par Email",
           "order_header": "Nouvelle commande depuis la liste de prix", "order_subject": "Nouvelle commande", "not_configured": "Coordonnées pour la commande pas encore configurées.", "total": "Total", "restricted_area": "Espace réservé fournisseur", "reference_label": "Client", "reference_placeholder": "non précisé", "package_of": "colis de", "packages_unit": "colis"},
    "es": {"title": "Gruppo Soria — Lista de precios Frutas y Verduras", "updated": "Actualizado el", "unavailable": "No disponible", "footer": "Precios indicativos, salida Volla (Nápoles, Italia), sujeto a confirmación de disponibilidad.",
           "order_title": "Tu pedido", "qty": "Cantidad", "no_items": "Selecciona arriba las cantidades de los productos que te interesan: aparecerán aquí.",
           "reference": "Tu nombre / empresa (opcional)", "send_whatsapp": "📲 Enviar pedido por WhatsApp", "send_email": "✉️ Enviar pedido por Email",
           "order_header": "Nuevo pedido desde la lista de precios", "order_subject": "Nuevo pedido", "not_configured": "Datos de contacto para el pedido aún no configurados.", "total": "Total", "restricted_area": "Área reservada proveedor", "reference_label": "Cliente", "reference_placeholder": "no especificado", "package_of": "paquete de", "packages_unit": "paquetes"},
    "pl": {"title": "Gruppo Soria — Cennik Owoców i Warzyw", "updated": "Zaktualizowano", "unavailable": "Niedostępne", "footer": "Ceny orientacyjne, loco Volla (Neapol, Włochy), z zastrzeżeniem dostępności.",
           "order_title": "Twoje zamówienie", "qty": "Ilość", "no_items": "Wybierz powyżej ilości interesujących Cię produktów: pojawią się tutaj.",
           "reference": "Twoje imię / firma (opcjonalnie)", "send_whatsapp": "📲 Wyślij zamówienie przez WhatsApp", "send_email": "✉️ Wyślij zamówienie e-mailem",
           "order_header": "Nowe zamówienie z cennika", "order_subject": "Nowe zamówienie", "not_configured": "Dane kontaktowe do zamówień nie zostały jeszcze skonfigurowane.", "total": "Razem", "restricted_area": "Strefa dostawcy", "reference_label": "Klient", "reference_placeholder": "nie podano", "package_of": "opakowanie", "packages_unit": "opakowania"},
    "el": {"title": "Gruppo Soria — Τιμοκατάλογος Οπωροκηπευτικών", "updated": "Ενημερώθηκε στις", "unavailable": "Μη διαθέσιμο", "footer": "Ενδεικτικές τιμές, εκ Volla (Νάπολη, Ιταλία), με την επιφύλαξη διαθεσιμότητας.",
           "order_title": "Η παραγγελία σας", "qty": "Ποσότητα", "no_items": "Επιλέξτε παραπάνω τις ποσότητες των προϊόντων που σας ενδιαφέρουν: θα εμφανιστούν εδώ.",
           "reference": "Όνομα / εταιρεία σας (προαιρετικό)", "send_whatsapp": "📲 Αποστολή παραγγελίας μέσω WhatsApp", "send_email": "✉️ Αποστολή παραγγελίας μέσω Email",
           "order_header": "Νέα παραγγελία από τον τιμοκατάλογο", "order_subject": "Νέα παραγγελία", "not_configured": "Τα στοιχεία επικοινωνίας για παραγγελίες δεν έχουν ρυθμιστεί ακόμα.", "total": "Σύνολο", "restricted_area": "Περιοχή προμηθευτή", "reference_label": "Πελάτης", "reference_placeholder": "δεν αναφέρθηκε", "package_of": "συσκευασία", "packages_unit": "συσκευασίες"},
    "pt": {"title": "Gruppo Soria — Lista de Preços Hortofrutícolas", "updated": "Atualizado em", "unavailable": "Indisponível", "footer": "Preços indicativos, saída de Volla (Nápoles, Itália), sujeitos a confirmação de disponibilidade.",
           "order_title": "O seu pedido", "qty": "Quantidade", "no_items": "Selecione acima as quantidades dos produtos que pretende: vão aparecer aqui.",
           "reference": "O seu nome / empresa (opcional)", "send_whatsapp": "📲 Enviar pedido via WhatsApp", "send_email": "✉️ Enviar pedido por Email",
           "order_header": "Novo pedido da lista de preços", "order_subject": "Novo pedido", "not_configured": "Contactos para pedidos ainda não configurados.", "total": "Total", "restricted_area": "Área reservada fornecedor", "reference_label": "Cliente", "reference_placeholder": "não especificado", "package_of": "embalagem de", "packages_unit": "embalagens"},
}

UNIT_LABELS = {
    "kg": {"it": "kg", "en": "kg", "fr": "kg", "es": "kg", "pl": "kg", "el": "κιλό", "pt": "kg"},
    "g": {"it": "g", "en": "g", "fr": "g", "es": "g", "pl": "g", "el": "γρ", "pt": "g"},
    "cassa": {"it": "cassa", "en": "box", "fr": "caisse", "es": "caja", "pl": "skrzynka", "el": "κιβώτιο", "pt": "caixa"},
    "testa": {"it": "testa", "en": "head", "fr": "pièce", "es": "unidad", "pl": "sztuka", "el": "τεμάχιο", "pt": "unidade"},
}
UNITS = ["kg", "g", "cassa", "testa"]

# Icona di fallback per categoria, usata quando un prodotto non ha una foto propria
CATEGORY_EMOJI = {
    "Pomodori": "🍅", "Peperoni": "🫑", "Melanzane": "🍆", "Zucchine e Cetrioli": "🥒",
    "Insalate e Verdure a Foglia": "🥬", "Agrumi": "🍊", "Mele e Pere": "🍎", "Frutta Estiva": "🍓",
    "Angurie e Meloni": "🍉", "Drupacee": "🍑", "Carciofi e Fagiolini": "🌱", "Radici e Tuberi": "🥔",
    "Erbe Aromatiche": "🌿", "Kiwi": "🥝",
}


def category_emoji(categoria):
    return CATEGORY_EMOJI.get(categoria, "📦")


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


@st.cache_data(ttl=120)
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
            "immagine_url": (r.get("immagine_url") or "").strip(),
            "confezione_kg": _parse_float_or_none(r.get("confezione_kg")),
        })
    products.sort(key=lambda p: p["ordine"])
    return products


@st.cache_data(ttl=300)
def load_categorie_trad():
    raw = api_get("categories")
    return {r["categoria"]: r for r in raw if r.get("categoria")}


@st.cache_data(ttl=120)
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

    # Lo storico viene registrato direttamente da Apps Script nella stessa
    # chiamata (se prezzo/unita'/peso cambiano) - non serve una seconda richiesta.
    result = api_post({"action": "update_product", "id": product_id, "updates": api_updates})
    return result is not None


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
    :root { color-scheme: dark; }
    .product-card {
        background: #F5F0E1; border-radius: 10px; padding: 12px 16px;
        margin-bottom: 8px; display: flex; justify-content: space-between; align-items: center; gap: 12px;
    }
    .product-card.unavailable { background: #E7E0CC; opacity: 0.65; }
    .product-icon { font-size: 1.6rem; line-height: 1; flex-shrink: 0; }
    .product-photo { width: 40px; height: 40px; border-radius: 8px; object-fit: cover; flex-shrink: 0; }
    .product-name { font-family: 'Oswald', sans-serif; font-weight: 600; text-transform: uppercase;
        letter-spacing: 0.03em; font-size: 0.92rem; color: #20291F; }
    .product-format { font-size: 0.78rem; color: #5B6B5D; margin-top: 2px; }
    .product-price { font-family: 'IBM Plex Mono', monospace; font-weight: 700; font-size: 1.05rem; color: #20291F; }
    .product-unit { font-size: 0.75rem; color: #5B6B5D; }
    .product-conv { font-family: 'IBM Plex Mono', monospace; font-size: 0.72rem; color: #B5790E; }
    .cat-header { font-family: 'Oswald', sans-serif; text-transform: uppercase; letter-spacing: 0.08em;
        font-size: 0.8rem; color: #F5F0E1; margin: 20px 0 8px 0; border-bottom: 1px solid #3A4A3D; padding-bottom: 4px; }
    .app-title { font-family: 'Oswald', sans-serif; color: #FBF8EF; text-transform: uppercase;
        font-weight: 700; letter-spacing: 0.02em; text-shadow: 0 1px 3px rgba(0,0,0,0.4); position: relative; }
    .app-title::after { content: ''; display: block; width: 64px; height: 4px; background: #D3A22C;
        border-radius: 2px; margin-top: 10px; }
    .footer-note { color: #8B968D; font-family: 'IBM Plex Mono', monospace; font-size: 0.72rem; text-align: center; margin-top: 24px; }
    .logo-row { display: flex; align-items: center; justify-content: center; gap: 28px; margin-bottom: 18px; flex-wrap: wrap; }
    .logo-row img { display: block; object-fit: contain; height: 42px; width: auto; }
    .contact-line { color: #A8B3A9; font-family: 'IBM Plex Mono', monospace; font-size: 0.78rem;
        margin: 10px 0 4px 0; display: flex; flex-wrap: wrap; gap: 4px 18px; align-items: center; }
    .contact-line a { color: #E0871F; text-decoration: none; }
    .contact-line a:hover { text-decoration: underline; }
    .cert-footer { background: #1F3128; border: 1px solid #3A4A3D; border-radius: 12px;
        padding: 18px 22px; margin-top: 28px; text-align: center; }
    .cert-footer-label { font-family: 'IBM Plex Mono', monospace; font-size: 0.7rem; text-transform: uppercase;
        letter-spacing: 0.12em; color: #8B968D; margin-bottom: 12px; display: block; }
    .cert-footer-logos { display: flex; align-items: center; justify-content: center; gap: 28px; flex-wrap: wrap; }
    .cert-badge { display: inline-flex; align-items: center; }
    .cert-badge img { height: 48px; width: auto; object-fit: contain; display: block;
        filter: drop-shadow(0 0 1px rgba(255,255,255,0.95)) drop-shadow(0 0 2px rgba(255,255,255,0.75)) drop-shadow(0 0 5px rgba(255,255,255,0.4)); }
    .cart-total { font-family: 'Oswald', sans-serif; color: #FBF8EF; font-size: 1.3rem; font-weight: 700;
        text-align: right; margin: 10px 0; padding-top: 10px; border-top: 2px solid #D3A22C; }
    .cart-total .amount { font-family: 'IBM Plex Mono', monospace; color: #D3A22C; }
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
if "cart" not in st.session_state:
    st.session_state.cart = {}

def render_supplier_access_control(lang="it"):
    """Piccolo accesso discreto in fondo alla pagina cliente, invece della sidebar."""
    t = UI[lang]
    _, col_center, _ = st.columns([3, 1, 3])
    with col_center:
        with st.popover("🔒", use_container_width=True):
            st.markdown(f"**{t['restricted_area']}**")
            pin_input = st.text_input("PIN", type="password", key="pin_input_popover", label_visibility="collapsed", placeholder="PIN")
            if st.button("Entra", key="entra_popover", use_container_width=True):
                if pin_input == SUPPLIER_PIN:
                    st.session_state.supplier_mode = True
                    st.rerun()
                else:
                    st.error("PIN errato.")


# ---------------------------------------------------------------------------
# Vista CLIENTE
# ---------------------------------------------------------------------------
def render_customer_view():
    lang = st.session_state.lang
    t = UI[lang]

    logos_html = "".join(
        f"<img src='data:image/{mime};base64,{b64}'>"
        for b64, mime in LOGOS if b64
    )
    if logos_html:
        st.markdown(f"<div class='logo-row'>{logos_html}</div>", unsafe_allow_html=True)

    st.markdown(f"<h1 class='app-title'>📦 {t['title']}</h1>", unsafe_allow_html=True)

    st.markdown(
        "<div class='contact-line'>"
        "<span>Export Manager: Pentti Salenius</span>"
        "<a href='tel:+393451077775'>📞 +39 345 107 7775</a>"
        "<a href='mailto:direzione@cooperativasoria.com'>✉️ direzione@cooperativasoria.com</a>"
        "</div>",
        unsafe_allow_html=True,
    )

    cert_html = "".join(
        f"<div class='cert-badge'><img src='data:image/{mime};base64,{b64}' title='{label}' alt='{label}'></div>"
        for b64, mime, label in CERT_LOGOS if b64
    )

    cols = st.columns(len(LANGUAGES))
    for i, (code, label) in enumerate(LANGUAGES):
        with cols[i]:
            if st.button(label, key=f"lang_{code}", type=("primary" if lang == code else "secondary"), use_container_width=True):
                st.session_state.lang = code
                st.rerun()

    all_products = load_products()
    # Ai clienti mostriamo solo i prodotti disponibili
    products = [p for p in all_products if p["disponibile"]]
    cat_trad = load_categorie_trad()
    storico = load_storico_recente()

    if not products:
        st.info("Nessun prodotto disponibile al momento (o problema di connessione al backend — controlla la sidebar per eventuali errori).")
        return

    categorie = {}
    for p in products:
        categorie.setdefault(p["categoria"], []).append(p)

    for categoria, items in categorie.items():
        st.markdown(f"<div class='cat-header'>{cat_label(categoria, cat_trad, lang)}</div>", unsafe_allow_html=True)
        for p in items:
            nome = name_label(p, lang)
            confezione = p.get("confezione_kg")
            vende_a_confezione = confezione and confezione > 0

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
            if p.get("immagine_url"):
                visual_html = f"<img class='product-photo' src='{p['immagine_url']}' alt='' onerror=\"this.outerHTML='<span class=product-icon>{category_emoji(p['categoria'])}</span>'\">"
            else:
                visual_html = f"<span class='product-icon'>{category_emoji(p['categoria'])}</span>"

            formato_display = p["formato"] or ""
            if vende_a_confezione:
                pkg_note = f"{t['package_of']} {confezione:g} kg"
                formato_display = f"{formato_display} · {pkg_note}" if formato_display else pkg_note

            card_html = (
                f"<div class='product-card'>"
                f"<div style='display:flex; align-items:center; gap:10px;'>{visual_html}"
                f"<div><div class='product-name'>{nome}</div><div class='product-format'>{formato_display}</div></div></div>"
                f"{right_html}</div>"
            )

            col_card, col_qty = st.columns([5, 1.3])
            with col_card:
                st.markdown(card_html, unsafe_allow_html=True)
            with col_qty:
                qty = st.number_input(
                    t["qty"], min_value=0, step=1, value=st.session_state.cart.get(p["id"], 0),
                    key=f"qty_{p['id']}", label_visibility="collapsed",
                )
                if vende_a_confezione:
                    st.caption(t["packages_unit"])
                    if qty > 0:
                        st.caption(f"= {qty * confezione:g} kg")
                else:
                    st.caption(unit_label(p["unita_base"], lang))
                st.session_state.cart[p["id"]] = qty

    st.markdown(f"<div class='footer-note'>{t['footer']}</div>", unsafe_allow_html=True)

    if cert_html:
        st.markdown(
            f"<div class='cert-footer'><span class='cert-footer-label'>Certificazioni</span>"
            f"<div class='cert-footer-logos'>{cert_html}</div></div>",
            unsafe_allow_html=True,
        )

    # -----------------------------------------------------------------
    # Riepilogo ordine
    # -----------------------------------------------------------------
    st.divider()
    st.markdown(f"<div class='cat-header'>🛒 {t['order_title']}</div>", unsafe_allow_html=True)

    products_by_id = {p["id"]: p for p in products}
    cart_lines = []
    grand_total = 0.0
    for pid, qty in st.session_state.cart.items():
        if qty and qty > 0 and pid in products_by_id:
            p = products_by_id[pid]
            confezione = p.get("confezione_kg")
            if confezione and confezione > 0:
                kg_totali = qty * confezione
                subtotal = kg_totali * p["prezzo_base"]
                grand_total += subtotal
                cart_lines.append(
                    f"- {name_label(p, lang)}: {qty} {t['packages_unit']} × {confezione:g}kg "
                    f"= {kg_totali:g}kg × {p['prezzo_base']:.2f}€/kg = {subtotal:.2f}€"
                )
            else:
                subtotal = qty * p["prezzo_base"]
                grand_total += subtotal
                cart_lines.append(
                    f"- {name_label(p, lang)}: {qty} {unit_label(p['unita_base'], lang)} "
                    f"× {p['prezzo_base']:.2f}€ = {subtotal:.2f}€"
                )

    if not cart_lines:
        st.caption(t["no_items"])
        render_supplier_access_control(lang)
        return

    riferimento = st.text_input(t["reference"], key="order_reference")

    order_body_preview = "\n".join(cart_lines) + f"\n\n{t['total']}: {grand_total:.2f}€"
    st.text_area(t["order_title"], order_body_preview, height=min(38 + 28 * len(cart_lines) + 30, 320), disabled=True, label_visibility="collapsed")
    st.markdown(f"<div class='cart-total'>{t['total']}: <span class='amount'>{grand_total:.2f} €</span></div>", unsafe_allow_html=True)

    nome_cliente = riferimento.strip() if riferimento.strip() else t["reference_placeholder"]
    full_message = f"{t['order_header']}\n{t['reference_label']}: {nome_cliente}\n\n{order_body_preview}"

    encoded_msg = urllib.parse.quote(full_message)

    if not ORDER_WHATSAPP_NUMBERS and not ORDER_EMAIL:
        st.warning(t["not_configured"])
    else:
        n_buttons = len(ORDER_WHATSAPP_NUMBERS) + (1 if ORDER_EMAIL else 0)
        btn_cols = st.columns(n_buttons)
        col_i = 0
        for i, number in enumerate(ORDER_WHATSAPP_NUMBERS):
            label = ORDER_WHATSAPP_LABELS[i] if i < len(ORDER_WHATSAPP_LABELS) else f"{i + 1}"
            wa_url = f"https://wa.me/{number}?text={encoded_msg}"
            with btn_cols[col_i]:
                st.link_button(f"📲 WhatsApp {label}", wa_url, use_container_width=True)
            col_i += 1
        if ORDER_EMAIL:
            mailto_url = f"mailto:{ORDER_EMAIL}?subject={urllib.parse.quote(t['order_subject'])}&body={encoded_msg}"
            with btn_cols[col_i]:
                st.link_button(t["send_email"], mailto_url, use_container_width=True)

    render_supplier_access_control(lang)


# ---------------------------------------------------------------------------
# Vista FORNITORE
# ---------------------------------------------------------------------------
def render_supplier_view():
    col_title, col_exit = st.columns([4, 1])
    with col_title:
        st.markdown("<h1 class='app-title'>🔧 Modalità fornitore</h1>", unsafe_allow_html=True)
    with col_exit:
        st.write("")
        if st.button("← Esci", use_container_width=True):
            st.session_state.supplier_mode = False
            st.rerun()
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
                    immagine_url = st.text_input(
                        "URL foto prodotto (facoltativo — se vuoto, mostra l'icona della categoria)",
                        value=p.get("immagine_url", ""), key=f"img_{p['id']}",
                        placeholder="https://...",
                    )

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

                    confezione_kg = None
                    if unita == "kg":
                        confezione_kg = st.number_input(
                            "Kg per confezione/cassa (facoltativo — se impostato, il cliente ordina 'a casse' invece che a kg diretti)",
                            value=float(p.get("confezione_kg") or 0), step=0.5, format="%.2f",
                            key=f"confezione_{p['id']}",
                        )
                        if confezione_kg and confezione_kg > 0:
                            st.caption(f"Il cliente vedrà: prezzo {prezzo:.2f} €/kg, e ordinerà a confezioni da {confezione_kg:g}kg "
                                       f"(es. 2 confezioni = {2*confezione_kg:g}kg = {2*confezione_kg*prezzo:.2f}€)")

                    save = st.form_submit_button("💾 Salva")
                    delete = st.form_submit_button("🗑️ Elimina prodotto")

                    if save:
                        updates = {
                            "nome": nome, "categoria": new_cat, "formato": formato,
                            "prezzo_base": prezzo, "unita_base": unita,
                            "peso_unitario_kg": peso if unita in ("cassa", "testa") else None,
                            "disponibile": disponibile, "immagine_url": immagine_url.strip(),
                            "confezione_kg": confezione_kg if (unita == "kg" and confezione_kg and confezione_kg > 0) else "",
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
