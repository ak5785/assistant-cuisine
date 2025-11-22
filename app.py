import streamlit as st
from google import genai
from google.genai import types
from notion_client import Client
import datetime
import json
import pandas as pd
import numpy as np

# --- CONFIGURATION INITIALE ---
st.set_page_config(page_title="Assistant Cuisine", page_icon="🥦", layout="wide")

# Récupération des clés secrètes (depuis Streamlit Secrets)
try:
    gemini_api_key = st.secrets["GEMINI_API_KEY"]
    notion_token = st.secrets["NOTION_TOKEN"]
    database_id = st.secrets["DATABASE_ID"]
except KeyError:
    st.error("Les clés API (GEMINI_API_KEY, NOTION_TOKEN, DATABASE_ID) ne sont pas configurées dans Streamlit Cloud Secrets.")
    st.stop()

# Initialisation des clients 
client_gemini = genai.Client(api_key=gemini_api_key)
# On force la version API
notion = Client(auth=notion_token, notion_version="2025-09-03")

# --- FONCTION DE CORRECTION DE L'ID (VERSION LA PLUS ROBUSTE) ---
@st.cache_resource
def format_database_id(id_string):
    """
    S'assure que l'ID de la base de données a le format UUID attendu (avec les tirets).
    Elle gère un ID déjà formaté ou un ID brut de 32 caractères.
    """
    id_string = id_string.strip() # Enlève tout espace au début/fin

    # Si l'ID est déjà au format UUID complet (36 caractères avec tirets), on le retourne
    if len(id_string) == 36 and id_string[8] == '-':
        return id_string
        
    # Nettoyage et vérification pour l'ID brut (32 caractères)
    id_string = id_string.replace('-', '')

    if len(id_string) == 32:
        return f"{id_string[:8]}-{id_string[8:12]}-{id_string[12:16]}-{id_string[16:20]}-{id_string[20:]}"
    
    return id_string # Retourne l'ID tel quel s'il est mal formé (ce qui causera une erreur plus tard)
# --- FIN DE LA CORRECTION ---


# --- RÈGLES DE CONSERVATION (LISTE DÉFINITIVE) ---
RULES = {
    "Viande": 2, "Légume": 5, "Fruit": 5, "Laitage": 7, "Sec": 365, "Autre": 3,    
    "Plat préparé": 4, "Produit laitier": 7, "Pâtisserie": 3, "Boulangerie": 2
}
# --- FIN DES RÈGLES ---

# --- RÉCUPÉRATION DES ARTICLES QUI EXPIRENT ---
@st.cache_data(ttl=60)
def get_expiring_items_from_notion(db_id, days_threshold=14):
    """
    Interroge Notion pour récupérer les articles en stock qui expirent bientôt.
    """
    
    formatted_id = format_database_id(db_id)
    seven_days_from_now = (datetime.date.today() + datetime.timedelta(days=days_threshold)).isoformat()
    
    # 1. Requête Notion pour filtrer les articles "En stock" et expirant "bientôt"
    try:
        # La méthode 'query' est la plus standard. Si l'erreur revient, la solution est le requirements.txt
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
        # Affiche l'erreur pour le débogage et donne la solution de contournement (requirements.txt)
        st.error(f"Erreur lors de la requête Notion (vérifiez les ID/Token/Partage de l'intégration) : {e}")
        st.error("❗ **Action requise** : Si l'erreur est '...has no attribute query', vous devez ajouter `notion-client==2.0.0` dans votre `requirements.txt`.")
        return pd.DataFrame() 

    # 2. Traitement des données
    items_list = []
    today = datetime.date.today()
    
    for page in response['results']:
        props = page['properties']
        
        try:
            # Extraction sécurisée des propriétés
            name_prop = props.get('Nom', {}).get('title', [{}])
            name = name_prop[0].get('plain_text', 'N/A') if name_prop and name_prop[0] else 'N/A'
            
            qty_prop = props.get('Quantité', {}).get('rich_text', [{}])
            qty = qty_prop[0].get('plain_text', 'N/A') if qty_prop and qty_prop[0] else 'N/A'
            
            category = props.get('Catégorie', {}).get('select', {}).get('name', 'N/A')
            expiry_date_str = props.get('Date Péremption', {}).get('date', {}).get('start', today.isoformat())
            
            # Calcul du nombre de jours restants
            expiry_date = datetime.date.fromisoformat(expiry_date_str)
            days_remaining = (expiry_date - today).days
            
            items_list.append({
                "Nom": name,
                "Quantité": qty,
                "Catégorie": category,
                "Date Péremption": expiry_date_str,
                "Jours Restants": days_remaining
            })
            
        except (AttributeError, IndexError, ValueError) as e:
            continue

    df = pd.DataFrame(items_list)
    
    if df.empty:
        return df

    df = df.sort_values(by="Jours Restants")
    return df

# --- FIN DE LA FONCTION DE RÉCUPÉRATION ---


# --- FONCTIONS GEMINI ET NOTION D'AJOUT ---
def analyze_image(image_file):
    """Analyse l'image avec Gemini."""
    image_bytes = image_file.getvalue()
    category_list = list(RULES.keys())

    prompt = f"""
    Analyse cette image de courses alimentaires. Identifie chaque aliment visible.
    Pour chaque aliment, retourne un objet JSON strict avec :
    - "nom": le nom de l'aliment (ex: "Tomates).
    - "quantite": une estimation de la quantité (ex: "6 unités" ou "500g").
    - "categorie": CHOISIS UNE SEULE OPTION PARMI : {category_list}.
    
    Retourne UNIQUEMENT une liste JSON brute, pas de markdown, pas de texte avant ou après.
    Exemple: [{{"nom": "Pomme", "quantite": "3", "categorie": "Fruit"}}]
    """
    
    image_part = types.Part.from_bytes(data=image_bytes, mime_type=image_file.type)
    
    response = client_gemini.models.generate_content(
        model='gemini-2.5-flash',
        contents=[prompt, image_part],
        config=types.GenerateContentConfig(
            response_mime_type="application/json"
        )
    )
    
    content = response.text.strip()
    
    if not content:
        st.warning("L'API Gemini a renvoyé une réponse vide.")
        return []

    try:
        data = json.loads(content)
        if isinstance(data, dict) and 'items' in data:
            return data['items']
        if isinstance(data, dict) and 'nom' in data: 
             return [data]
        return data
    except Exception as e:
        st.error(f"Erreur de lecture JSON par l'IA: {e}. Contenu reçu: {content[:200]}...")
        return []


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
# --- FIN DES AUTRES FONCTIONS ---


# --- LOGIQUE DE STYLE DU TABLEAU ---
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
st.title("📸 Scanner de Frigo")

# --- SECTION D'ALERTE ---
st.header("🛒 État du Garde-Manger")
st.markdown("---")

with st.spinner("Chargement des alertes de péremption depuis Notion..."):
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
# --- FIN DE LA SECTION D'ALERTE ---


# --- SECTION D'UPLOAD ---
st.header("➕ Ajouter des Courses")
uploaded_file = st.file_uploader("Prends une photo de tes courses", type=["jpg", "png", "jpeg"])

if uploaded_file:
    st.image(uploaded_file, caption="Image analysée", use_container_width=True)
    
    if st.button("🔍 Analyser avec l'IA"):
        st.session_state.pop('scanned_items', None)
        st.session_state.pop('validated_items', None)

        with st.spinner("Analyse en cours par Gemini-2.5-Flash..."):
            try:
                data = analyze_image(uploaded_file)
                if data:
                    st.session_state['scanned_items'] = data
                    st.session_state['validated_items'] = [item.copy() for item in data]
                    st.success(f"{len(data)} aliments détectés et prêts à être validés !")
                else:
                    st.warning("Aucun aliment détecté ou l'IA n'a pas retourné de JSON valide.")
            except Exception as e:
                st.error(f"Une erreur inattendue est survenue lors de l'analyse : {e}")


if 'scanned_items' in st.session_state:
    st.subheader("Validation avant export vers Notion")
    
    category_options = list(RULES.keys())

    with st.form("validation_form"):
        st.write("Modifiez les noms ou catégories si l'IA s'est trompée.")
        
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
                    st.warning(f"Impossible d'ajouter '{item['nom']}' à Notion. Erreur : {e}")
                
                progress_bar.progress((idx + 1) / len(items_to_save))
            
            if success_count == len(items_to_save):
                st.success(f"Stock mis à jour dans Notion ! ({success_count} articles ajoutés)")
            else:
                 st.warning(f"{success_count} articles ajoutés. Veuillez vérifier l'orthographe exacte des colonnes dans Notion et le partage de l'intégration.")
            
            st.session_state.pop('scanned_items', None)
            st.session_state.pop('validated_items', None)
# --- FIN DE LA SECTION D'UPLOAD ---
