import streamlit as st
from google import genai
from google.genai import types
from notion_client import Client
import datetime
import json
import pandas as pd
import base64
import requests

# ------------------------------------------------------------
# 🔧 CONFIGURATION DE L'APPLICATION
# ------------------------------------------------------------

st.set_page_config(page_title="Assistant Cuisine", page_icon="🥦", layout="wide")

# Récupération des clés dans Streamlit Secrets
try:
    gemini_api_key = st.secrets.get("GEMINI_API_KEY")
    notion_token = st.secrets["NOTION_TOKEN"]
    database_id = st.secrets["DATABASE_ID"]
    claude_api_key = st.secrets.get("CLAUDE_API_KEY")
    openai_api_key = st.secrets.get("OPENAI_API_KEY")
except KeyError as e:
    st.error(f"❌ Clé manquante dans Streamlit Secrets : {e}")
    st.stop()

# Initialisation Notion
notion = Client(auth=notion_token)

# Initialisation Gemini
client_gemini = None
if gemini_api_key:
    client_gemini = genai.Client(api_key=gemini_api_key)

# Liste des catégories et durées automatiques
RULES = {
    "Viande": 2,
    "Légume": 5,
    "Fruit": 5,
    "Laitage": 7,
    "Sec": 365,
    "Autre": 3,
    "Plat préparé": 4,
    "Produit laitier": 7,
    "Pâtisserie": 3,
    "Boulangerie": 2
}

# ------------------------------------------------------------
# 🔧 UTILITAIRES
# ------------------------------------------------------------

def format_database_id(id_string):
    """Nettoie l'ID Notion."""
    return id_string.replace('-', '').replace(' ', '').strip()

# ------------------------------------------------------------
# 🥫 RÉCUPÉRATION DES ARTICLES QUI EXPIRENT
# ------------------------------------------------------------

@st.cache_data(ttl=60)
def get_expiring_items_from_notion(db_id, days_threshold=14):
    """Retourne les produits qui expirent dans <days_threshold> jours."""
    formatted_id = format_database_id(db_id)
    date_limit = (datetime.date.today() + datetime.timedelta(days=days_threshold)).isoformat()

    try:
        response = notion.databases.query(
            database_id=formatted_id,
            filter={
                "and": [
                    {"property": "Statut", "select": {"equals": "En stock"}},
                    {"property": "Date_Péremption", "date": {"on_or_before": date_limit}}
                ]
            }
        )
    except Exception as e:
        st.error(f"Erreur Notion : {e}")
        return pd.DataFrame()

    items = []
    today = datetime.date.today()

    for page in response['results']:
        props = page['properties']

        name_prop = props.get("Nom", {}).get("title", [{}])
        name = name_prop[0].get("plain_text", "N/A") if name_prop else "N/A"

        qty_prop = props.get("Quantité", {}).get("rich_text", [{}])
        qty = qty_prop[0].get("plain_text", "N/A") if qty_prop else "N/A"

        cat = props.get("Catégorie", {}).get("select", {}).get("name", "N/A")

        expiry_str = props.get("Date_Péremption", {}).get("date", {}).get("start", today.isoformat())
        expiry_date = datetime.date.fromisoformat(expiry_str)
        days_left = (expiry_date - today).days

        items.append({
            "Nom": name,
            "Quantité": qty,
            "Catégorie": cat,
            "Date_Péremption": expiry_str,
            "Jours Restants": days_left
        })

    df = pd.DataFrame(items)
    if df.empty:
        return df

    return df.sort_values("Jours Restants")

# ------------------------------------------------------------
# 🤖 IA — ANALYSE DES IMAGES
# ------------------------------------------------------------

def analyze_with_gemini(image_file):
    if not client_gemini:
        raise ValueError("Clé Gemini manquante.")

    image_bytes = image_file.getvalue()
    categories = list(RULES.keys())

    prompt = f"""
    Analyse cette image et retourne uniquement un JSON :
    [
      {{"nom": "...", "quantite": "...", "categorie": "{categories}"}}
    ]
    """

    image_part = types.Part.from_bytes(data=image_bytes, mime_type=image_file.type)

    models = [
        "gemini-2.0-flash-exp",
        "gemini-1.5-flash-8b",
        "gemini-1.5-flash"
    ]

    last_error = None
    for model in models:
        try:
            res = client_gemini.models.generate_content(
                model=model,
                contents=[prompt, image_part],
                config=types.GenerateContentConfig(response_mime_type="application/json")
            )
            data = json.loads(res.text.strip())
            if isinstance(data, dict) and "items" in data:
                return data["items"]
            if isinstance(data, dict):
                return [data]
            return data
        except Exception as e:
            last_error = e
            continue

    raise Exception(f"Gemini a échoué. Dernière erreur: {last_error}")


def analyze_with_claude(image_file):
    if not claude_api_key:
        raise ValueError("Clé Claude manquante.")

    img_b64 = base64.b64encode(image_file.getvalue()).decode()
    categories = list(RULES.keys())

    prompt = f"""
    Retourne uniquement un JSON :
    [
      {{"nom":"...", "quantite":"...", "categorie":"{categories}"}}
    ]
    """

    headers = {
        "x-api-key": claude_api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json"
    }

    data = {
        "model": "claude-3-5-sonnet-20241022",
        "max_tokens": 2048,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": image_file.type, "data": img_b64}},
                {"type": "text", "text": prompt}
            ]
        }]
    }

    res = requests.post("https://api.anthropic.com/v1/messages", headers=headers, json=data)
    if res.status_code != 200:
        raise Exception(res.text)

    txt = res.json()["content"][0]["text"]
    txt = txt.replace("```json", "").replace("```", "").strip()

    return json.loads(txt)


def analyze_with_openai(image_file):
    if not openai_api_key:
        raise ValueError("Clé OpenAI manquante.")

    img_b64 = base64.b64encode(image_file.getvalue()).decode()
    categories = list(RULES.keys())

    prompt = f"""
    Retourne uniquement un JSON :
    [
      {{"nom":"...", "quantite":"...", "categorie":"{categories}"}}
    ]
    """

    headers = {"Authorization": f"Bearer {openai_api_key}", "Content-Type": "application/json"}

    payload = {
        "model": "gpt-4o-mini",
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:{image_file.type};base64,{img_b64}"}}
            ]
        }],
        "max_tokens": 2048
    }

    res = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload)
    if res.status_code != 200:
        raise Exception(res.text)

    txt = res.json()["choices"][0]["message"]["content"]
    txt = txt.replace("```json", "").replace("```", "").strip()

    return json.loads(txt)


def analyze_image(image_file, ai_choice):
    if ai_choice == "Gemini (Google)":
        return analyze_with_gemini(image_file)
    if ai_choice == "Claude (Anthropic)":
        return analyze_with_claude(image_file)
    if ai_choice == "GPT-4 Vision (OpenAI)":
        return analyze_with_openai(image_file)
    raise ValueError("IA inconnue.")

# ------------------------------------------------------------
# 📝 AJOUT DANS NOTION
# ------------------------------------------------------------

def add_to_notion(item):
    """Ajoute un élément dans Notion avec délai + date calculée."""
    formatted_id = format_database_id(database_id)

    days = item.get("delai", RULES.get(item["categorie"], 3))
    expiry_date = (datetime.date.today() + datetime.timedelta(days=days)).isoformat()

    notion.pages.create(
        parent={"database_id": formatted_id},
        properties={
            "Nom": {"title": [{"text": {"content": item["nom"]}}]},
            "Quantité": {"rich_text": [{"text": {"content": item["quantite"]}}]},
            "Catégorie": {"select": {"name": item["categorie"]}},
            "Statut": {"select": {"name": "En stock"}},
            "Délai (jours)": {"number": days},   # ← nouvelle propriété
            "Date_Péremption": {"date": {"start": expiry_date}}
        }
    )
# ------------------------------------------------------------
# 🖥️ INTERFACE STREAMLIT — SCAN IA
# ------------------------------------------------------------

st.title("📸 Scanner de Frigo Multi-IA")

# IA disponibles
available_ais = []
if gemini_api_key:
    available_ais.append("Gemini (Google)")
if claude_api_key:
    available_ais.append("Claude (Anthropic)")
if openai_api_key:
    available_ais.append("GPT-4 Vision (OpenAI)")

if not available_ais:
    st.error("❌ Aucune IA n'est disponible. Configurez une clé API.")
    st.stop()

# ------------------------------------------------------------
# 🧊 AFFICHAGE DES ARTICLES QUI EXPIRENT
# ------------------------------------------------------------

st.header("🛒 État du Garde-Manger")
st.markdown("---")

with st.spinner("Chargement..."):
    expiring_df = get_expiring_items_from_notion(database_id)

def highlight_expiry(s):
    """Coloration selon le niveau d'urgence."""
    if s["Jours Restants"] < 0:
        return ['background-color:#F8BBD0;color:#D32F2F'] * len(s)
    if s["Jours Restants"] <= 3:
        return ['background-color:#FFE0B2;color:#E65100'] * len(s)
    if s["Jours Restants"] <= 7:
        return ['background-color:#FFF9C4;color:#FBC02D'] * len(s)
    return [''] * len(s)

if not expiring_df.empty:
    st.subheader("⚠️ Articles expirant bientôt")
    styled = expiring_df.style.apply(highlight_expiry, axis=1)
    st.dataframe(styled, use_container_width=True, hide_index=True)
else:
    st.success("🎉 Aucun produit n'expire dans les 14 prochains jours.")

st.markdown("---")

# ------------------------------------------------------------
# 📤 UPLOAD + ANALYSE IA
# ------------------------------------------------------------

st.header("➕ Ajouter des Courses (via Photo)")

ai_choice = st.selectbox("🤖 Choisissez l'IA", available_ais)

uploaded_file = st.file_uploader("Prends une photo (jpg/png/jpeg)", type=["jpg", "jpeg", "png"])

if uploaded_file:
    st.image(uploaded_file, caption="Image chargée", use_container_width=True)

    if st.button(f"🔍 Analyser avec {ai_choice}"):
        st.session_state.pop("scanned_items", None)

        with st.spinner("Analyse en cours..."):
            try:
                data = analyze_image(uploaded_file, ai_choice)
                if data:
                    st.session_state["scanned_items"] = data
                    st.success(f"✨ {len(data)} aliments détectés !")
                else:
                    st.warning("Aucun aliment détecté.")
            except Exception as e:
                st.error(f"Erreur IA : {e}")

# ------------------------------------------------------------
# 📝 VALIDATION DES ALIMENTS DÉTECTÉS
# ------------------------------------------------------------

if "scanned_items" in st.session_state:
    st.subheader("Validation des Aliments Détectés")

    category_options = list(RULES.keys())

    with st.form("validation_form"):
        items_to_save = []

        for i, item in enumerate(st.session_state["scanned_items"]):

            # Délai calculé automatiquement selon la catégorie
            auto_days = RULES.get(item.get("categorie"), 3)

            try:
                default_index = category_options.index(item["categorie"])
            except ValueError:
                default_index = category_options.index("Autre")

            # Colonnes : nom / quantité / catégorie
            c1, c2, c3 = st.columns([2, 1, 1])
            # Colonnes : délai / preview date
            c4, c5 = st.columns([1, 1])

            with c1:
                nom = st.text_input(f"Nom #{i+1}", value=item["nom"], key=f"v_nom_{i}")

            with c2:
                qty = st.text_input(f"Qté #{i+1}", value=item["quantite"], key=f"v_qty_{i}")

            with c3:
                cat = st.selectbox(
                    f"Catégorie #{i+1}",
                    category_options,
                    index=default_index,
                    key=f"v_cat_{i}"
                )

            # Délai auto + modifiable
            with c4:
                delai = st.number_input(
                    f"Délai (jours) #{i+1}",
                    min_value=1,
                    max_value=30,
                    value=auto_days,
                    step=1,
                    key=f"v_delai_{i}"
                )

            # Preview de la date de péremption
            with c5:
                preview = (datetime.date.today() + datetime.timedelta(days=delai)).isoformat()
                st.write(f"📅 **Expire : {preview}**")

            items_to_save.append({
                "nom": nom,
                "quantite": qty,
                "categorie": cat,
                "delai": delai,
                "expiry": preview
            })

        # Bouton de validation
        submitted = st.form_submit_button("📤 Envoyer vers Notion")

        if submitted:
            ok = 0
            for item in items_to_save:
                try:
                    add_to_notion(item)
                    ok += 1
                except Exception as e:
                    st.error(f"Erreur pour {item['nom']} : {e}")

            if ok > 0:
                st.success(f"✅ {ok} articles ajoutés dans Notion !")
                st.balloons()

            st.session_state.pop("scanned_items", None)
            st.rerun()
# ------------------------------------------------------------
# 📝 AJOUT MANUEL D'ALIMENTS
# ------------------------------------------------------------

st.markdown("---")
st.header("✏️ Ajouter Manuellement des Aliments")

# Initialisation des lignes si pas déjà présent
if "manual_items" not in st.session_state:
    st.session_state.manual_items = [{
        "nom": "",
        "quantite": "",
        "categorie": "Autre",
        "delai": 3
    }]

# Bouton : Ajouter une nouvelle ligne
if st.button("➕ Ajouter une ligne"):
    st.session_state.manual_items.append({
        "nom": "",
        "quantite": "",
        "categorie": "Autre",
        "delai": 3
    })

# Formulaire d'ajout manuel
with st.form("manual_form"):
    st.write("Ajoutez autant de produits que vous le souhaitez.")

    updated_manual_items = []

    for i, item in enumerate(st.session_state.manual_items):

        # Auto-delay selon catégorie
        auto_days = RULES.get(item["categorie"], 3)

        # Colonnes : nom / quantité / catégorie / délai / preview date
        c1, c2, c3, c4, c5 = st.columns([2, 1, 1, 1, 1])

        with c1:
            nom = st.text_input(
                f"Nom #{i+1}",
                value=item["nom"],
                key=f"man_nom_{i}"
            )

        with c2:
            qty = st.text_input(
                f"Qté #{i+1}",
                value=item["quantite"],
                key=f"man_qty_{i}"
            )

        with c3:
            cat = st.selectbox(
                f"Catégorie #{i+1}",
                list(RULES.keys()),
                index=list(RULES.keys()).index(item["categorie"]) if item["categorie"] in RULES else 0,
                key=f"man_cat_{i}"
            )

        with c4:
            delai = st.number_input(
                f"Jours #{i+1}",
                min_value=1,
                max_value=30,
                value=item.get("delai", auto_days),
                step=1,
                key=f"man_delai_{i}"
            )

        with c5:
            preview = (datetime.date.today() + datetime.timedelta(days=delai)).isoformat()
            st.write(f"📅 {preview}")

        updated_manual_items.append({
            "nom": nom,
            "quantite": qty,
            "categorie": cat,
            "delai": delai,
            "expiry": preview
        })

    st.session_state.manual_items = updated_manual_items

    manual_submit = st.form_submit_button("📤 Ajouter dans Notion")

    if manual_submit:
        ok = 0
        for item in st.session_state.manual_items:
            try:
                add_to_notion(item)
                ok += 1
            except Exception as e:
                st.error(f"❌ Erreur pour {item['nom']} : {e}")

        if ok > 0:
            st.success(f"✅ {ok} articles ajoutés dans Notion !")
            st.balloons()

        # Reset après ajout
        st.session_state.manual_items = [{
            "nom": "",
            "quantite": "",
            "categorie": "Autre",
            "delai": 3
        }]
        st.rerun()

# ------------------------------------------------------------
# 🎉 FIN DU SCRIPT
# ------------------------------------------------------------

st.write("---")
st.info("Assistant Cuisine — Optimisé, Automatisé et Connecté à Notion 🍏")
