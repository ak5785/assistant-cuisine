import streamlit as st
from google import genai
from google.genai import types
from notion_client import Client
import datetime
import json
import base64

# --- CONFIGURATION INITIALE ---
st.set_page_config(page_title="Assistant Cuisine", page_icon="🥦")

# Récupération des clés secrètes (depuis Streamlit Secrets)
try:
    gemini_api_key = st.secrets["GEMINI_API_KEY"]
    notion_token = st.secrets["NOTION_TOKEN"]
    database_id = st.secrets["DATABASE_ID"]
except KeyError:
    st.error("Les clés API (GEMINI_API_KEY, NOTION_TOKEN, DATABASE_ID) ne sont pas configurées dans Streamlit Cloud Secrets. Veuillez vérifier les 'Advanced settings' de votre application.")
    st.stop()

# Initialisation des clients 
client_gemini = genai.Client(api_key=gemini_api_key)
# On force la version API et on utilise le jeton ntn_
notion = Client(auth=notion_token, notion_version="2025-09-03")

# --- FONCTION DE CORRECTION DE L'ID (CRITIQUE pour l'erreur de format) ---
def format_database_id(id_string):
    """
    S'assure que l'ID de la base de données a le format UUID attendu (avec les tirets).
    Ceci corrige l'erreur où l'ID est copié sans les tirets.
    """
    id_string = id_string.replace('-', '').strip() # Nettoyage initial
    if len(id_string) == 32:
        return f"{id_string[:8]}-{id_string[8:12]}-{id_string[12:16]}-{id_string[16:20]}-{id_string[20:]}"
    return id_string
# --- FIN DE LA CORRECTION ---


# --- RÈGLES DE CONSERVATION (LISTE DÉFINITIVE ET ÉTENDUE DES CATÉGORIES) ---
RULES = {
    # Catégories de base
    "Viande": 2,
    "Légume": 5,
    "Fruit": 5,
    "Laitage": 7,  
    "Sec": 365,    
    "Autre": 3,    
    
    # Catégories étendues (selon votre demande)
    "Plat préparé": 4, 
    "Produit laitier": 7, 
    "Pâtisserie": 3,
    "Boulangerie": 2
}
# --- FIN DES RÈGLES ---

def analyze_image(image_file):
    """Envoie l'image à Gemini pour analyse et retourne un JSON."""
    
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
    
    response = client_gemini.models.generate_content(
        model='gemini-2.5-flash',
        contents=[prompt, image_part],
        config=types.GenerateContentConfig(
            response_mime_type="application/json"
        )
    )
    
    content = response.text.strip()
    
    if not content:
        st.warning("L'API Gemini a renvoyé une réponse vide (vérifiez votre clé ou votre solde).")
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
    
    # 1. Utilise la fonction de formatage pour l'ID
    formatted_id = format_database_id(database_id) 

    # 2. Calcul de la date
    days = RULES.get(item['categorie'], 3)
    expiry_date = (datetime.date.today() + datetime.timedelta(days=days)).isoformat()
    
    # 3. Appel à Notion (utilise database_id pour corriger l'erreur de validation 'parent')
    notion.pages.create(
        parent={"database_id": formatted_id},
        properties={
            # Ces noms de colonnes DOIVENT correspondre EXACTEMENT (casse/accents) à Notion
            "Nom": {"title": [{"text": {"content": item['nom']}}]},
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
    
    # Les options sont extraites des clés du dictionnaire RULES
    category_options = list(RULES.keys())

    with st.form("validation_form"):
        st.write("Modifiez les noms ou catégories si l'IA s'est trompée.")
        
        items_to_save = []
        for i, item in enumerate(st.session_state['scanned_items']):
            try:
                # S'assurer que la catégorie renvoyée par l'IA existe dans notre liste
                default_index = category_options.index(item['categorie'])
            except ValueError:
                # Si l'IA invente une catégorie, on utilise 'Autre' par défaut
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
                 # Le message d'avertissement est conservé pour les problèmes potentiels de propriétés (faute de frappe)
                 st.warning(f"{success_count} articles ajoutés. Vérifiez l'orthographe exacte des colonnes dans Notion et que l'intégration est partagée.")
            
            st.session_state.pop('scanned_items', None)
            st.session_state.pop('validated_items', None)
