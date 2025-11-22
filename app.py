import streamlit as st
from openai import OpenAI
from notion_client import Client
import datetime
import json
import base64

# --- CONFIGURATION INITIALE ---
st.set_page_config(page_title="Assistant Cuisine", page_icon="🥦")

# Récupération des clés secrètes (depuis Streamlit Secrets)
try:
    openai_api_key = st.secrets["OPENAI_API_KEY"]
    notion_token = st.secrets["NOTION_TOKEN"]
    database_id = st.secrets["DATABASE_ID"]
except KeyError:
    st.error("Les clés API (OPENAI_API_KEY, NOTION_TOKEN, DATABASE_ID) ne sont pas configurées dans Streamlit Cloud Secrets. Veuillez vérifier les 'Advanced settings' de votre application.")
    st.stop()

# Initialisation des clients avec la nouvelle version d'API pour le jeton ntn_
client_openai = OpenAI(api_key=openai_api_key)
# FORCER LA VERSION API POUR SUPPORTER LES JETONS ntn_ et la nouvelle structure de BDD
notion = Client(auth=notion_token, notion_version="2025-09-03")

# Règles de conservation (Jours supplémentaires au-delà d'aujourd'hui)
RULES = {
    "Viande": 2,
    "Légume": 5,
    "Fruit": 5,
    "Laitage": 7,
    "Sec": 365,
    "Autre": 3
}

def analyze_image(image_file):
    """Envoie l'image à GPT-4o-mini pour analyse et retourne un JSON."""
    
    # 1. Encodage de l'image en Base64
    bytes_data = image_file.getvalue()
    base64_image = base64.b64encode(bytes_data).decode('utf-8')

    # 2. Le Prompt pour l'IA (Doit être strict pour garantir le JSON)
    prompt = """
    Analyse cette image de courses alimentaires. Identifie chaque aliment visible.
    Pour chaque aliment, retourne un objet JSON strict avec :
    - "nom": le nom de l'aliment (ex: "Tomates").
    - "quantite": une estimation de la quantité (ex: "6 unités" ou "500g").
    - "categorie": CHOISIS UNE SEULE OPTION PARMI : ["Viande", "Légume", "Fruit", "Laitage", "Sec", "Autre"].
    
    Retourne UNIQUEMENT une liste JSON brute, pas de markdown, pas de texte avant ou après.
    Exemple: [{"nom": "Pomme", "quantite": "3", "categorie": "Fruit"}]
    """

    response = client_openai.chat.completions.create(
        model="gpt-4o-mini",  # Modèle rapide et efficace pour la vision
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{base64_image}"
                        }
                    }
                ],
            }
        ],
        max_tokens=500,
        response_format={"type": "json_object"} # Force le JSON
    )
    
    # 3. Nettoyage et Parsing du JSON
    content = response.choices[0].message.content
    try:
        data = json.loads(content)
        # S'assurer que le résultat est bien une liste si l'IA l'a enveloppé
        if isinstance(data, dict) and 'items' in data:
            return data['items']
        return data
    except Exception as e:
        st.error(f"Erreur de lecture JSON par l'IA: {e}. Contenu reçu: {content[:200]}...")
        return []

def add_to_notion(item):
    """Ajoute un élément validé dans Notion."""
    # Calcul de la date de péremption basée sur les règles
    days = RULES.get(item['categorie'], 3)
    expiry_date = (datetime.date.today() + datetime.timedelta(days=days)).isoformat()
    
    notion.pages.create(
        parent={"database_id": database_id},
        properties={
            # Titre de la page (colonne "Nom")
            "Nom": {"title": [{"text": {"content": item['nom']}}]},
            
            # Autres propriétés (vérifier la casse et les accents!)
            "Quantité": {"rich_text": [{"text": {"content": item['quantite']}}]},
            "Catégorie": {"select": {"name": item['categorie']}},
            "Statut": {"select": {"name": "En stock"}},
            "Date Péremption": {"date": {"start": expiry_date}}
        }
    )

# --- INTERFACE STREAMLIT ---
st.title("📸 Scanner de Frigo")

uploaded_file = st.file_uploader("Prends une photo de tes courses", type=["jpg", "png", "jpeg"])

if uploaded_file:
    st.image(uploaded_file, caption="Image analysée", use_container_width=True)
    
    if st.button("🔍 Analyser avec l'IA"):
        # Reset l'état précédent
        st.session_state.pop('scanned_items', None)
        st.session_state.pop('validated_items', None)

        with st.spinner("Analyse en cours par GPT-4o-mini..."):
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

# Affichage et Validation
if 'scanned_items' in st.session_state:
    st.subheader("Validation avant export vers Notion")
    
    # Options de sélection à utiliser dans le formulaire
    category_options = ["Viande", "Légume", "Fruit", "Laitage", "Sec", "Autre"]

    # Utilisation d'un formulaire pour la validation
    with st.form("validation_form"):
        st.write("Modifiez les noms ou catégories si l'IA s'est trompée.")
        
        # Le formulaire reconstruit les données dans validated_items
        items_to_save = []
        for i, item in enumerate(st.session_state['scanned_items']):
            # Tente de trouver l'index de la catégorie détectée par l'IA
            try:
                default_index = category_options.index(item['categorie'])
            except ValueError:
                default_index = category_options.index("Autre") # Catégorie par défaut si l'IA se trompe

            c1, c2, c3 = st.columns([2, 1, 1])
            with c1:
                name = st.text_input(f"Nom #{i+1}", value=item.get('nom', ''), key=f"name_{i}")
            with c2:
                qty = st.text_input(f"Qté #{i+1}", value=item.get('quantite', ''), key=f"qty_{i}")
            with c3:
                cat = st.selectbox(f"Catégorie #{i+1}", category_options, index=default_index
