import streamlit as st
from google import genai
from google.genai import types
from notion_client import Client
import datetime
import json
import pandas as pd
import base64
import requests

# --- CONFIGURATION INITIALE ---
st.set_page_config(page_title="Assistant Cuisine", page_icon="🥦", layout="wide")

# Récupération des clés secrètes
try:
    gemini_api_key = st.secrets.get("GEMINI_API_KEY")
    notion_token = st.secrets["NOTION_TOKEN"]
    database_id = st.secrets["DATABASE_ID"]
    claude_api_key = st.secrets.get("CLAUDE_API_KEY")
    openai_api_key = st.secrets.get("OPENAI_API_KEY")
except KeyError as e:
    st.error(f"Clé manquante dans Streamlit Secrets : {e}")
    st.stop()

# Initialisation du client Notion
notion = Client(auth=notion_token)

# Initialisation du client Gemini (si disponible)
client_gemini = None
if gemini_api_key:
    client_gemini = genai.Client(api_key=gemini_api_key)

# --- FONCTION DE CORRECTION DE L'ID ---
def format_database_id(id_string):
    """Nettoie l'ID en retirant tous les tirets et espaces."""
    cleaned_id = id_string.replace('-', '').replace(' ', '').strip()
    return cleaned_id

# --- RÈGLES DE CONSERVATION ---
RULES = {
    "Viande": 2, "Légume": 5, "Fruit": 5, "Laitage": 7, "Sec": 365, "Autre": 3,    
    "Plat préparé": 4, "Produit laitier": 7, "Pâtisserie": 3, "Boulangerie": 2
}

# --- RÉCUPÉRATION DES ARTICLES QUI EXPIRENT ---
@st.cache_data(ttl=60)
def get_expiring_items_from_notion(db_id, days_threshold=14):
    """Interroge Notion pour récupérer les articles en stock qui expirent bientôt."""
    formatted_id = format_database_id(db_id)
    seven_days_from_now = (datetime.date.today() + datetime.timedelta(days=days_threshold)).isoformat()
    
    try:
        response = notion.databases.query( 
            database_id=formatted_id,
            filter={
                "and": [
                    {
                        "property": "Statut",
                        "select": {
                            "equals": "En stock"
                        }
                    },
                    {
                        "property": "Date Péremption",
                        "date": {
                            "on_or_before": seven_days_from_now
                        }
                    }
                ]
            }
        )
    except Exception as e:
        st.error(f"❌ Erreur Notion : {e}")
        st.info("💡 Vérifiez que l'intégration est bien connectée à votre base Notion (••• → Connections)")
        return pd.DataFrame() 

    # Traitement des données
    items_list = []
    today = datetime.date.today()
    
    for page in response['results']:
        props = page['properties']
        
        try:
            name_prop = props.get('Nom', {}).get('title', [{}])
            name = name_prop[0].get('plain_text', 'N/A') if name_prop and name_prop[0] else 'N/A'
            
            qty_prop = props.get('Quantité', {}).get('rich_text', [{}])
            qty = qty_prop[0].get('plain_text', 'N/A') if qty_prop and qty_prop[0] else 'N/A'
            
            category = props.get('Catégorie', {}).get('select', {}).get('name', 'N/A')
            expiry_date_str = props.get('Date Péremption', {}).get('date', {}).get('start', today.isoformat())
            
            expiry_date = datetime.date.fromisoformat(expiry_date_str)
            days_remaining = (expiry_date - today).days
            
            items_list.append({
                "Nom": name,
                "Quantité": qty,
                "Catégorie": category,
                "Date Péremption": expiry_date_str,
                "Jours Restants": days_remaining
            })
        except (AttributeError, IndexError, ValueError):
            continue

    df = pd.DataFrame(items_list)
    
    if df.empty:
        return df

    df = df.sort_values(by="Jours Restants")
    return df

# --- FONCTIONS D'ANALYSE PAR IA ---

def analyze_with_gemini(image_file):
    """Analyse l'image avec Gemini."""
    if not client_gemini:
        raise ValueError("Clé API Gemini non configurée")
    
    image_bytes = image_file.getvalue()
    category_list = list(RULES.keys())

    prompt = f"""
    Analyse cette image de courses alimentaires. Identifie chaque aliment visible.
    Pour chaque aliment, retourne un objet JSON strict avec :
    - "nom": le nom de l'aliment (ex: "Tomates").
    - "quantite": une estimation de la quantité (ex: "6 unités" ou "500g").
    - "categorie": CHOISIS UNE SEULE OPTION PARMI : {category_list}.
    
    Retourne UNIQUEMENT une liste JSON brute, pas de markdown, pas de texte avant ou après.
    Exemple: [{{"nom": "Pomme", "quantite": "3", "categorie": "Fruit"}}]
    """
    
    image_part = types.Part.from_bytes(data=image_bytes, mime_type=image_file.type)
    
    # Essayer plusieurs modèles Gemini jusqu'à ce qu'un fonctionne
    models_to_try = [
        'gemini-1.5-flash-8b',
        'gemini-1.5-flash-latest', 
        'gemini-1.5-flash',
    ]
    
    last_error = None
    for model in models_to_try:
        try:
            response = client_gemini.models.generate_content(
                model=model,
                contents=[prompt, image_part],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json"
                )
            )
            
            content = response.text.strip()
            
            if not content:
                continue

            data = json.loads(content)
            if isinstance(data, dict) and 'items' in data:
                return data['items']
            if isinstance(data, dict) and 'nom' in data: 
                return [data]
            return data
            
        except Exception as e:
            last_error = e
            continue
    
    # Si tous les modèles ont échoué
    raise Exception(f"Tous les modèles Gemini ont échoué. Dernière erreur: {last_error}")


def analyze_with_claude(image_file):
    """Analyse l'image avec Claude via l'API Anthropic."""
    if not claude_api_key:
        raise ValueError("Clé API Claude non configurée")
    
    image_bytes = image_file.getvalue()
    base64_image = base64.b64encode(image_bytes).decode('utf-8')
    category_list = list(RULES.keys())
    
    prompt = f"""Analyse cette image de courses alimentaires. Identifie chaque aliment visible.
    Pour chaque aliment, retourne un objet JSON avec :
    - "nom": le nom de l'aliment
    - "quantite": une estimation de la quantité
    - "categorie": choisis parmi {category_list}
    
    Retourne UNIQUEMENT un array JSON, sans markdown ni texte supplémentaire.
    Format: [{{"nom": "Pomme", "quantite": "3", "categorie": "Fruit"}}]"""
    
    headers = {
        "x-api-key": claude_api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json"
    }
    
    data = {
        "model": "claude-3-5-sonnet-20241022",
        "max_tokens": 2048,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": image_file.type,
                            "data": base64_image
                        }
                    },
                    {
                        "type": "text",
                        "text": prompt
                    }
                ]
            }
        ]
    }
    
    response = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers=headers,
        json=data
    )
    
    if response.status_code != 200:
        raise Exception(f"Erreur API Claude: {response.text}")
    
    result = response.json()
    content = result['content'][0]['text'].strip()
    
    # Nettoyage du markdown si présent
    content = content.replace('```json', '').replace('```', '').strip()
    
    try:
        data = json.loads(content)
        if isinstance(data, dict) and 'items' in data:
            return data['items']
        if isinstance(data, dict) and 'nom' in data:
            return [data]
        return data
    except Exception as e:
        st.error(f"Erreur de lecture JSON Claude : {e}")
        return []


def analyze_with_openai(image_file):
    """Analyse l'image avec GPT-4 Vision."""
    if not openai_api_key:
        raise ValueError("Clé API OpenAI non configurée")
    
    image_bytes = image_file.getvalue()
    base64_image = base64.b64encode(image_bytes).decode('utf-8')
    category_list = list(RULES.keys())
    
    prompt = f"""Analyse cette image de courses alimentaires. Identifie chaque aliment visible.
    Pour chaque aliment, retourne un objet JSON avec :
    - "nom": le nom de l'aliment
    - "quantite": une estimation de la quantité
    - "categorie": choisis parmi {category_list}
    
    Retourne UNIQUEMENT un array JSON, sans markdown ni texte supplémentaire.
    Format: [{{"nom": "Pomme", "quantite": "3", "categorie": "Fruit"}}]"""
    
    headers = {
        "Authorization": f"Bearer {openai_api_key}",
        "Content-Type": "application/json"
    }
    
    data = {
        "model": "gpt-4o-mini",  # Modèle plus économique
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": prompt
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{image_file.type};base64,{base64_image}"
                        }
                    }
                ]
            }
        ],
        "max_tokens": 2048
    }
    
    response = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers=headers,
        json=data
    )
    
    if response.status_code != 200:
        raise Exception(f"Erreur API OpenAI: {response.text}")
    
    result = response.json()
    content = result['choices'][0]['message']['content'].strip()
    
    # Nettoyage du markdown si présent
    content = content.replace('```json', '').replace('```', '').strip()
    
    try:
        data = json.loads(content)
        if isinstance(data, dict) and 'items' in data:
            return data['items']
        if isinstance(data, dict) and 'nom' in data:
            return [data]
        return data
    except Exception as e:
        st.error(f"Erreur de lecture JSON OpenAI : {e}")
        return []


def analyze_image(image_file, ai_choice):
    """Analyse l'image avec l'IA choisie."""
    if ai_choice == "Gemini (Google)":
        return analyze_with_gemini(image_file)
    elif ai_choice == "Claude (Anthropic)":
        return analyze_with_claude(image_file)
    elif ai_choice == "GPT-4 Vision (OpenAI)":
        return analyze_with_openai(image_file)
    else:
        raise ValueError(f"IA non supportée: {ai_choice}")


def add_to_notion(item):
    """Ajoute un élément validé dans Notion."""
    formatted_id = format_database_id(database_id) 

    days = RULES.get(item['categorie'], 3)
    expiry_date = (datetime.date.today() + datetime.timedelta(days=days)).isoformat()
    
    notion.pages.create(
        parent={"database_id": formatted_id},
        properties={
            "Nom": {"title": [{"text": {"content": item['nom']}}]},
            "Quantité": {"rich_text": [{"text": {"content": item['quantite']}}]},
            "Catégorie": {"select": {"name": item['categorie']}},
            "Statut": {"select": {"name": "En stock"}},
            "Date Péremption": {"date": {"start": expiry_date}}
        }
    )

# --- STYLE DU TABLEAU ---
def highlight_expiry(s):
    """Applique une couleur d'arrière-plan en fonction de l'urgence."""
    is_expired = s["Jours Restants"] < 0
    is_urgent = (s["Jours Restants"] >= 0) & (s["Jours Restants"] <= 3)
    is_soon = (s["Jours Restants"] > 3) & (s["Jours Restants"] <= 7)
    
    if is_expired:
        return ['background-color: #F8BBD0; color: #D32F2F'] * len(s)
    elif is_urgent:
        return ['background-color: #FFE0B2; color: #E65100'] * len(s)
    elif is_soon:
        return ['background-color: #FFF9C4; color: #FBC02D'] * len(s)
    else:
        return [''] * len(s)

# --- INTERFACE STREAMLIT ---
st.title("📸 Scanner de Frigo Multi-IA")

# Détection des IA disponibles
available_ais = []
if gemini_api_key:
    available_ais.append("Gemini (Google)")
if claude_api_key:
    available_ais.append("Claude (Anthropic)")
if openai_api_key:
    available_ais.append("GPT-4 Vision (OpenAI)")

if not available_ais:
    st.error("❌ Aucune clé API d'IA configurée. Ajoutez au moins GEMINI_API_KEY, CLAUDE_API_KEY ou OPENAI_API_KEY dans vos secrets.")
    st.stop()

# Affichage des IA disponibles
with st.sidebar:
    st.header("🤖 Configuration IA")
    st.write("**IA disponibles:**")
    for ai in available_ais:
        st.success(f"✅ {ai}")
    
    if len(available_ais) < 3:
        st.info("💡 Ajoutez les clés manquantes dans Secrets pour débloquer plus d'options")
        st.markdown("""
        **Pour ajouter des IA :**
        - **Claude** : [console.anthropic.com](https://console.anthropic.com)
        - **OpenAI** : [platform.openai.com](https://platform.openai.com)
        """)

# --- SECTION D'ALERTE ---
st.header("🛒 État du Garde-Manger")
st.markdown("---")

with st.spinner("Chargement des alertes..."):
    expiring_df = get_expiring_items_from_notion(database_id)

if not expiring_df.empty:
    styled_df = expiring_df.style.apply(highlight_expiry, axis=1)
    st.subheader("⚠️ Articles Expirant Bientôt (J-14)")
    st.dataframe(
        styled_df, 
        use_container_width=True,
        hide_index=True,
        column_order=("Nom", "Quantité", "Catégorie", "Date Péremption", "Jours Restants")
    )
else:
    st.info("Aucun article n'expire dans les 14 prochains jours. Tout est sous contrôle ! 👍")

st.markdown("---")

# --- SECTION D'UPLOAD ---
st.header("➕ Ajouter des Courses")

# Sélection de l'IA
ai_choice = st.selectbox(
    "🤖 Choisissez l'IA pour l'analyse",
    available_ais,
    help="Sélectionnez l'intelligence artificielle qui analysera votre image"
)

uploaded_file = st.file_uploader("Prends une photo de tes courses", type=["jpg", "png", "jpeg"])

if uploaded_file:
    st.image(uploaded_file, caption="Image analysée", use_container_width=True)
    
    if st.button(f"🔍 Analyser avec {ai_choice}"):
        st.session_state.pop('scanned_items', None)
        st.session_state.pop('validated_items', None)

        with st.spinner(f"Analyse en cours avec {ai_choice}..."):
            try:
                data = analyze_image(uploaded_file, ai_choice)
                if data:
                    st.session_state['scanned_items'] = data
                    st.session_state['validated_items'] = [item.copy() for item in data]
                    st.success(f"✨ {len(data)} aliments détectés par {ai_choice} !")
                else:
                    st.warning("Aucun aliment détecté.")
            except Exception as e:
                error_msg = str(e)
                if "429" in error_msg or "quota" in error_msg.lower():
                    st.error("⏳ Quota Gemini dépassé. Essayez Claude ou GPT-4, ou attendez quelques minutes.")
                else:
                    st.error(f"Erreur lors de l'analyse : {e}")

if 'scanned_items' in st.session_state:
    st.subheader("Validation avant export vers Notion")
    
    category_options = list(RULES.keys())

    with st.form("validation_form"):
        st.write("Modifiez les informations si nécessaire.")
        
        items_to_save = []
        for i, item in enumerate(st.session_state['scanned_items']):
            try:
                default_index = category_options.index(item['categorie'])
            except ValueError:
                default_index = category_options.index("Autre")

            c1, c2, c3 = st.columns([2, 1, 1])
            with c1:
                name = st.text_input(f"Nom #{i+1}", value=item.get('nom', ''), key=f"name_{i}")
            with c2:
                qty = st.text_input(f"Qté #{i+1}", value=item.get('quantite', ''), key=f"qty_{i}")
            with c3:
                cat = st.selectbox(f"Catégorie #{i+1}", category_options, index=default_index, key=f"cat_{i}") 
            
            items_to_save.append({"nom": name, "quantite": qty, "categorie": cat})
        
        submitted = st.form_submit_button("✅ Valider et Envoyer vers Notion")
        
        if submitted:
            progress_bar = st.progress(0)
            success_count = 0
            
            for idx, item in enumerate(items_to_save):
                try:
                    add_to_notion(item)
                    success_count += 1
                except Exception as e:
                    st.warning(f"Impossible d'ajouter '{item['nom']}' : {e}")
                
                progress_bar.progress((idx + 1) / len(items_to_save))
            
            if success_count == len(items_to_save):
                st.success(f"✅ {success_count} articles ajoutés à Notion !")
                st.balloons()
            else:
                st.warning(f"⚠️ {success_count}/{len(items_to_save)} articles ajoutés.")
            
            st.session_state.pop('scanned_items', None)
            st.session_state.pop('validated_items', None)
            st.rerun()
