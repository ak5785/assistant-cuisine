import streamlit as st
from notion_client import Client
from google import genai
from google.genai import types
import datetime
import json
import pandas as pd
import requests
import base64

# ------------------------------------------------------------
# 🔧 CONFIGURATION GÉNÉRALE
# ------------------------------------------------------------

st.set_page_config(page_title="Assistant Cuisine", page_icon="🍽️", layout="wide")

# Chargement des clés API
try:
    gemini_api_key = st.secrets.get("GEMINI_API_KEY")
    claude_api_key = st.secrets.get("CLAUDE_API_KEY")
    openai_api_key = st.secrets.get("OPENAI_API_KEY")
    notion_token = st.secrets["NOTION_TOKEN"]
    database_id = st.secrets["DATABASE_ID"]
except KeyError as e:
    st.error(f"❌ Clé manquante dans Streamlit Secrets : {e}")
    st.stop()

# Clients Notion & Gemini
notion = Client(auth=notion_token)
client_gemini = genai.Client(api_key=gemini_api_key) if gemini_api_key else None

# ------------------------------------------------------------
# 🧂 RÈGLES POUR LES DÉLAIS PAR DÉFAUT SELON CATÉGORIE
# ------------------------------------------------------------

RULES = {
    "Viande": 2,
    "Volaille": 2,
    "Poisson": 1,
    "Légume": 5,
    "Fruit": 5,
    "Laitage": 7,
    "Produit laitier": 7,
    "Sec": 365,
    "Pâtisserie": 3,
    "Boulangerie": 2,
    "Plat préparé": 4,
    "Autre": 3
}

# ------------------------------------------------------------
# 🧪 INGREDIENTS SECONDAIRES NON BLOQUANTS
# ------------------------------------------------------------

SECONDARY_INGREDIENTS = [
    "sel", "poivre", "épice", "épices", "curcuma", "paprika", "cumin", "herbes",
    "huile", "huile d’olive", "vinaigre", "beurre", "citron", "ail", "oignon",
    "levure", "sucre", "bouillon", "épices", "herbes de provence",
    "sauce soja", "sauce", "miel", "épices"
]

# ------------------------------------------------------------
# 🔧 OUTILS UTILES
# ------------------------------------------------------------

def format_database_id(id_string):
    """Supprime les tirets inutiles dans l’ID."""
    return id_string.replace('-', '').strip()


# ------------------------------------------------------------
# 📦 INVENTAIRE COMPLET POUR LE MENU & LES RECETTES
# ------------------------------------------------------------

def get_full_inventory_from_notion(db_id):
    """Retourne tout l'inventaire 'En stock'."""
    formatted_id = format_database_id(db_id)

    try:
        response = notion.databases.query(
            database_id=formatted_id,
            filter={
                "property": "Statut",
                "select": {"equals": "En stock"}
            }
        )
    except Exception as e:
        st.error(f"❌ Erreur Notion : {e}")
        return pd.DataFrame()

    items = []
    today = datetime.date.today()

    for page in response["results"]:
        props = page["properties"]

        name = props["Nom"]["title"][0]["plain_text"] if props["Nom"]["title"] else "Sans nom"
        qty = props["Quantité"]["rich_text"][0]["plain_text"] if props["Quantité"]["rich_text"] else "1"
        cat = props["Catégorie"]["select"]["name"] if props["Catégorie"]["select"] else "Autre"

        expiry_str = props.get("Date_Péremption", {}).get("date", {}).get("start", None)

        if expiry_str:
            try:
                expiry_date = datetime.date.fromisoformat(expiry_str)
                days_left = (expiry_date - today).days
            except:
                expiry_date = None
                days_left = None
        else:
            expiry_date = None
            days_left = None

        items.append({
            "Nom": name,
            "Quantité": qty,
            "Catégorie": cat,
            "Date_Péremption": expiry_str,
            "Jours Restants": days_left
        })

    df = pd.DataFrame(items)
    if "Jours Restants" in df.columns:
        df = df.sort_values("Jours Restants", na_position="last")

    return df


# ------------------------------------------------------------
# 🧠 ANALYSE IMAGE — IA (Gemini / Claude / GPT-4)
# ------------------------------------------------------------

def analyze_with_gemini(image_file):
    if not client_gemini:
        raise ValueError("Clé API Gemini manquante.")

    image_bytes = image_file.getvalue()
    categories = list(RULES.keys())

    prompt = f"""
Analyse cette image et retourne uniquement un JSON sous forme :
[
  {{
    "nom": "...",
    "quantite": "...",
    "categorie": "{categories}"
  }}
]
"""

    image_part = types.Part.from_bytes(data=image_bytes, mime_type=image_file.type)

    try:
        res = client_gemini.models.generate_content(
            model="gemini-2.0-flash-exp",
            contents=[prompt, image_part],
            config=types.GenerateContentConfig(response_mime_type="application/json")
        )
        txt = res.text.strip()
        data = json.loads(txt)

        # Corrections formats Gemini
        if isinstance(data, dict) and "items" in data:
            return data["items"]
        if isinstance(data, dict):
            return [data]
        return data

    except Exception as e:
        raise Exception(f"Erreur Gemini : {e}")


def analyze_with_claude(image_file):
    if not claude_api_key:
        raise ValueError("Clé API Claude manquante.")

    img_b64 = base64.b64encode(image_file.getvalue()).decode()
    categories = list(RULES.keys())

    prompt = f"""
Retourne uniquement un JSON:
[
  {{
    "nom":"...",
    "quantite":"...",
    "categorie":"{categories}"
  }}
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
Retourne uniquement un JSON:
[
  {{
    "nom":"...",
    "quantite":"...",
    "categorie":"{categories}"
  }}
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
# 📝 AJOUT D'UN PRODUIT DANS NOTION
# ------------------------------------------------------------

def add_to_notion(item):
    """Ajoute un produit avec délai, statut et date de péremption."""
    formatted_id = format_database_id(database_id)
    days = item.get("delai", RULES.get(item["categorie"], 3))
    expiry = (datetime.date.today() + datetime.timedelta(days=days)).isoformat()

    notion.pages.create(
        parent={"database_id": formatted_id},
        properties={
            "Nom": {"title": [{"text": {"content": item["nom"]}}]},
            "Quantité": {"rich_text": [{"text": {"content": item["quantite"]}}]},
            "Catégorie": {"select": {"name": item["categorie"]}},
            "Statut": {"select": {"name": "En stock"}},
            "Délai (jours)": {"number": days},
            "Date_Péremption": {"date": {"start": expiry}}
        }
    )
# ------------------------------------------------------------
# 🖼️ INTERFACE — SCAN PAR IA (PHOTO)
# ------------------------------------------------------------

st.header("📸 Ajouter des aliments via une photo")

available_ais = []
if gemini_api_key:
    available_ais.append("Gemini (Google)")
if claude_api_key:
    available_ais.append("Claude (Anthropic)")
if openai_api_key:
    available_ais.append("GPT-4 Vision (OpenAI)")

if not available_ais:
    st.error("❌ Aucune IA disponible. Configure les clés API.")
    st.stop()

ai_choice = st.selectbox("Choisissez l’IA pour analyser l’image :", available_ais)

uploaded_file = st.file_uploader("Télécharge une photo (jpg/jpeg/png)", type=["jpg", "jpeg", "png"])

if uploaded_file:
    st.image(uploaded_file, use_container_width=True, caption="Image chargée")

    if st.button(f"🔍 Analyser l'image avec {ai_choice}"):
        st.session_state.pop("scanned_items", None)
        with st.spinner("Analyse en cours..."):
            try:
                items = analyze_image(uploaded_file, ai_choice)
                st.session_state["scanned_items"] = items
                st.success(f"{len(items)} aliment(s) détecté(s) 🎉")
            except Exception as e:
                st.error(f"Erreur IA : {e}")


# ------------------------------------------------------------
# 📝 VALIDATION DES ALIMENTS DETECTÉS
# ------------------------------------------------------------

if "scanned_items" in st.session_state:

    st.subheader("📝 Validation des aliments détectés")
    category_options = list(RULES.keys())

    with st.form("validation_form"):

        items_to_save = []

        for i, item in enumerate(st.session_state["scanned_items"]):

            auto_days = RULES.get(item.get("categorie", "Autre"), 3)

            try:
                default_cat = category_options.index(item.get("categorie", "Autre"))
            except ValueError:
                default_cat = category_options.index("Autre")

            c1, c2, c3 = st.columns([2, 1, 1])
            c4, c5 = st.columns([1, 1])

            with c1:
                nom = st.text_input(
                    f"Nom #{i+1}",
                    value=item.get("nom", ""),
                    key=f"det_nom_{i}"
                )

            with c2:
                qty = st.text_input(
                    f"Quantité #{i+1}",
                    value=item.get("quantite", ""),
                    key=f"det_qty_{i}"
                )

            with c3:
                cat = st.selectbox(
                    f"Catégorie #{i+1}",
                    category_options,
                    index=default_cat,
                    key=f"det_cat_{i}"
                )

            # Délai automatique mais modifiable
            with c4:
                delai = st.number_input(
                    f"Jours #{i+1}",
                    min_value=1,
                    max_value=30,
                    value=auto_days,
                    step=1,
                    key=f"det_days_{i}"
                )

            # Preview date péremption
            with c5:
                preview = (datetime.date.today() + datetime.timedelta(days=delai)).isoformat()
                st.write(f"📅 {preview}")

            items_to_save.append({
                "nom": nom,
                "quantite": qty,
                "categorie": cat,
                "delai": delai,
                "expiry": preview
            })

        submitted = st.form_submit_button("📤 Ajouter dans Notion")

        if submitted:
            success = 0
            for item in items_to_save:
                try:
                    add_to_notion(item)
                    success += 1
                except Exception as e:
                    st.error(f"Erreur : {e}")

            if success > 0:
                st.success(f"✅ {success} aliment(s) ajouté(s) dans Notion !")
                st.balloons()

            st.session_state.pop("scanned_items", None)
            st.rerun()
# ------------------------------------------------------------
# 📝 AJOUT MANUEL D'ALIMENTS
# ------------------------------------------------------------

st.header("✏️ Ajouter manuellement des aliments")

# Initialisation des lignes si aucune
if "manual_items" not in st.session_state:
    st.session_state.manual_items = [{
        "nom": "",
        "quantite": "",
        "categorie": "Autre",
        "delai": 3
    }]

# Bouton → ajouter une nouvelle ligne
if st.button("➕ Ajouter une ligne"):
    st.session_state.manual_items.append({
        "nom": "",
        "quantite": "",
        "categorie": "Autre",
        "delai": 3
    })

with st.form("manual_form"):
    updated_items = []

    for i, item in enumerate(st.session_state.manual_items):

        auto_days = RULES.get(item["categorie"], 3)

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

        updated_items.append({
            "nom": nom,
            "quantite": qty,
            "categorie": cat,
            "delai": delai,
            "expiry": preview
        })

    st.session_state.manual_items = updated_items

    submitted_manual = st.form_submit_button("📤 Ajouter dans Notion")

    if submitted_manual:
        success = 0
        for item in st.session_state.manual_items:
            try:
                add_to_notion(item)
                success += 1
            except Exception as e:
                st.error(f"Erreur : {e}")

        if success > 0:
            st.success(f"✅ {success} aliments ajoutés dans Notion !")
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
# 🕒 AFFICHAGE — PRODUITS EXPIRANT BIENTÔT
# ------------------------------------------------------------

st.markdown("---")
st.header("🛒 État du garde-manger (anti-gaspi)")

@st.cache_data(ttl=60)
def get_expiring_items(db_id, days_threshold=14):
    """Retourne les aliments dont la date est ≤ limite."""
    formatted_id = format_database_id(db_id)
    limit = (datetime.date.today() + datetime.timedelta(days=days_threshold)).isoformat()

    try:
        response = notion.databases.query(
            database_id=formatted_id,
            filter={
                "and": [
                    {"property": "Statut", "select": {"equals": "En stock"}},
                    {"property": "Date_Péremption", "date": {"on_or_before": limit}}
                ]
            }
        )
    except Exception as e:
        st.error(f"Erreur Notion : {e}")
        return pd.DataFrame()

    today = datetime.date.today()
    items = []

    for page in response["results"]:
        props = page["properties"]

        name = props["Nom"]["title"][0]["plain_text"] if props["Nom"]["title"] else "Sans nom"
        qty = props["Quantité"]["rich_text"][0]["plain_text"] if props["Quantité"]["rich_text"] else ""
        cat = props["Catégorie"]["select"]["name"] if props["Catégorie"]["select"] else "Autre"

        expiry_str = props.get("Date_Péremption", {}).get("date", {}).get("start", None)

        if expiry_str:
            expiry = datetime.date.fromisoformat(expiry_str)
            days_left = (expiry - today).days
        else:
            days_left = None

        items.append({
            "Nom": name,
            "Quantité": qty,
            "Catégorie": cat,
            "Date_Péremption": expiry_str,
            "Jours Restants": days_left
        })

    df = pd.DataFrame(items)

    if not df.empty:
        df = df.sort_values("Jours Restants", na_position="last")

    return df


# Récupération des items expirant
expiring = get_expiring_items(database_id)

def highlight_row(row):
    """Coloration selon l’urgence."""
    if row["Jours Restants"] is None:
        return [""] * len(row)
    if row["Jours Restants"] < 0:
        return ["background-color:#F8BBD0; color:#B71C1C"] * len(row)
    if row["Jours Restants"] <= 2:
        return ["background-color:#FFCDD2; color:#C62828"] * len(row)
    if row["Jours Restants"] <= 5:
        return ["background-color:#FFE0B2; color:#E65100"] * len(row)
    if row["Jours Restants"] <= 10:
        return ["background-color:#FFF9C4; color:#F9A825"] * len(row)
    return [""] * len(row)

if expiring.empty:
    st.success("🎉 Aucun produit n’expire dans les 14 prochains jours.")
else:
    styled = expiring.style.apply(highlight_row, axis=1)
    st.dataframe(styled, use_container_width=True, hide_index=True)

st.markdown("---")
# ------------------------------------------------------------
# 🧠 MENU INTELLIGENT ANTI-GASPI
# ------------------------------------------------------------

st.header("🧠 Menu intelligent anti-gaspi")

with st.expander("Paramètres du menu", expanded=True):

    menu_ai_choice = st.selectbox(
        "IA utilisée pour générer le menu :",
        available_ais
    )

    nb_days = st.slider(
        "Durée du menu (jours) :",
        min_value=3, max_value=7, value=5
    )

    nb_people = st.number_input(
        "Nombre de personnes :", min_value=1, max_value=12, value=2
    )

    style_menu = st.selectbox(
        "Style de menu souhaité :",
        ["Équilibré", "Rapide", "Économique", "Gourmand", "Healthy", "Végétarien", "Surprise"]
    )

    restrictions = st.text_input(
        "Restrictions alimentaires (optionnel) :",
        placeholder="ex : sans lactose, sans porc, végé…"
    )


# ------------------------------------------------------------
# 🧠 FONCTION IA POUR GÉNÉRER LE MENU COMPLET
# ------------------------------------------------------------

def generate_menu_ai(inventory_df, ai, nb_days, nb_people, style, restrictions):
    """
    Génère un menu complet + liste de courses IA.
    Avec règles anti-gaspi + ingrédients secondaires non bloquants.
    """

    if inventory_df.empty:
        raise ValueError("Inventaire vide.")

    # Convertit l’inventaire en texte structuré
    inv_lines = []
    for _, row in inventory_df.iterrows():
        inv_lines.append(
            f"- {row['Nom']} | qté: {row['Quantité']} | cat: {row['Catégorie']} | jours restants: {row['Jours Restants']}"
        )
    inv_text = "\n".join(inv_lines)

    # Prompt IA complet
    prompt = f"""
Tu es un chef spécialisé en cuisine anti-gaspi.

Voici mon inventaire :
{inv_text}

Consigne :

1. Propose un **menu complet sur {nb_days} jours** pour **{nb_people} personnes**.
2. Pour **chaque jour**, propose :
   - Petit-déjeuner
   - Déjeuner
   - Dîner
   - 1 collation ou dessert
3. Style de menu : {style}
4. Restrictions : {restrictions if restrictions else "aucune"}

⛔ IMPORTANT — Gestion des ingrédients manquants :

Ne rejette JAMAIS une recette si un ingrédient secondaire manque.
Un ingrédient secondaire = tout ce qui n’est pas essentiel à la structure du plat 
(ex : condiment, épice, assaisonnement, herbe, matière grasse, sucre, petit ajout facultatif).

Si un ingrédient secondaire manque : 
- ignore-le, OU 
- propose une alternative simple.

Un ingrédient essentiel = l’élément principal du plat (protéine, légume majeur, féculent, base indispensable).
S’il manque un ingrédient essentiel : 
- conserve la recette, 
- ajoute seulement cet ingrédient dans la section “🛒 Liste de courses complémentaire”.

Ne jamais abandonner une recette à cause d’un ingrédient facultatif.

Format strict :

### 🧠 Menu anti-gaspi (sur {nb_days} jours)
(Jours détaillés + recettes + ingrédients principaux + instructions)

### 🛒 Liste de courses complémentaire
- ingrédient (quantité estimée)
- ingrédient …
"""

    # ---- IA Gemini ----
    if ai == "Gemini (Google)":
        res = client_gemini.models.generate_content(
            model="gemini-2.0-flash-exp", contents=prompt
        )
        return res.text.strip()

    # ---- IA Claude ----
    if ai == "Claude (Anthropic)":
        headers = {
            "x-api-key": claude_api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        }
        data = {
            "model": "claude-3-5-sonnet-20241022",
            "max_tokens": 3500,
            "messages": [{"role": "user", "content": prompt}]
        }
        res = requests.post("https://api.anthropic.com/v1/messages", headers=headers, json=data)
        return res.json()["content"][0]["text"].strip()

    # ---- IA GPT-4 (OpenAI) ----
    if ai == "GPT-4 Vision (OpenAI)":
        headers = {"Authorization": f"Bearer {openai_api_key}", "Content-Type": "application/json"}
        data = {
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 3500
        }
        res = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=data)
        return res.json()["choices"][0]["message"]["content"].strip()

    raise ValueError("IA non reconnue")


# ------------------------------------------------------------
# 🛒 LISTE DE COURSES AUTOMATIQUE (calculée par ton app)
# ------------------------------------------------------------

def compute_missing_ingredients(menu_text, inventory_df):
    """
    Analyse le texte du menu + l'inventaire
    et crée une liste d'ingrédients ESSENTIELS manquants.
    """

    existing = [str(x).lower() for x in inventory_df["Nom"].tolist()]

    lines = menu_text.lower().split("\n")
    missing = []

    # On scan toutes les lignes contenant "ingrédient"
    for line in lines:
        if any(w in line for w in ["ingr", "ingredient", "ingrédients"]):

            # extraction simple
            words = line.replace(":", " ").replace(",", " ").split()

            for w in words:
                # filtre basique contre mots sans importance
                if len(w) < 4:
                    continue

                # ignore ingrédients secondaires
                if any(sec in w for sec in SECONDARY_INGREDIENTS):
                    continue

                # si ce n'est pas dans l'inventaire → manquant
                if w not in existing and w not in missing:
                    missing.append(w)

    return missing


# ------------------------------------------------------------
# 🎛️ BOUTON — GÉNÉRATION DU MENU
# ------------------------------------------------------------

if st.button("🍽️ Générer le menu intelligent anti-gaspi"):

    with st.spinner("Analyse de l’inventaire..."):
        inventory_df = get_full_inventory_from_notion(database_id)

    if inventory_df.empty:
        st.error("Aucun produit 'En stock' dans Notion.")
    else:
        with st.spinner("Génération du menu en cours..."):

            try:
                menu_ai_text = generate_menu_ai(
                    inventory_df,
                    menu_ai_choice,
                    nb_days,
                    nb_people,
                    style_menu,
                    restrictions
                )

                st.subheader("📋 Menu anti-gaspi généré par l’IA")
                st.markdown(menu_ai_text)

                # ----------------------
                # Liste de courses auto
                # ----------------------

                missing = compute_missing_ingredients(menu_ai_text, inventory_df)

                st.subheader("🛒 Liste de courses automatique (calcul fiable)")

                if not missing:
                    st.success("🎉 Rien à acheter ! Vous avez tout pour cuisiner ce menu.")
                else:
                    for item in missing:
                        st.write(f"- {item}")

            except Exception as e:
                st.error(f"Erreur IA : {e}")

st.markdown("---")
st.info("Assistant Cuisine — Menu intelligent anti-gaspi 🍽️")
