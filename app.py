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

# Initialisation des clients avec la nouvelle version d'API Notion
client_gemini = genai.Client(api_key=gemini_api_key)
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
    """Envoie l'image à Gemini pour analyse et retourne un JSON."""
    
    # Lecture des bytes de l'image
    image_bytes = image_file.getvalue()

    # 1. Préparation du contenu (texte + image) pour Gemini
    prompt = """
    Analyse cette image de courses alimentaires. Identifie chaque aliment visible.
    Pour chaque aliment, retourne un objet JSON strict avec :
    - "nom": le nom de l'aliment (ex: "Tomates").
    - "quantite": une estimation de la quantité (ex: "6 unités" ou "500g").
    - "categorie": CHOISIS UNE SEULE OPTION PARMI : ["Viande", "Légume", "Fruit", "Laitage", "Sec", "Autre"].
    
    Retourne UNIQUEMENT une liste JSON brute, pas de markdown, pas de texte avant ou après.
    Exemple: [{"nom": "Pomme", "quantite": "3", "categorie": "Fruit"}]
    """
    
    # Crée l'objet image pour l'API Gemini
    image_part = types.Part.from_bytes(data=image_bytes, mime_type=image_file.type)
    
    # 2. Appel à l'API Gemini
    response = client_gemini.models.generate_content(
        model='gemini-2.5-flash',
        contents=[prompt, image_part],
        config=types.GenerateContentConfig(
            response_mime_type="application/json" # Demande explicitement du JSON
        )
    )
    
    # 3. Nettoyage et Parsing du JSON
    content = response.text.strip()
    
    if not content:
        st.warning("L'API Gemini a renvoyé une réponse vide (vérifiez votre clé ou votre solde).")
        return []

    try:
        # Tente de charger le JSON
        data = json.loads(content)
        
        # S'assurer que le résultat est bien une liste (même si l'IA l'a enveloppé)
        if isinstance(data, dict) and 'items' in data:
            return data['items']
        return data
    except Exception as e:
        st.error(f"Erreur de lecture JSON par l'IA: {e}. Contenu reçu: {content[:200]}...")
        return []

def add_to_notion(item):
    """Ajoute un élément validé dans Notion. Identique à la version précédente."""
    
    days = RULES.get(item['categorie'], 3)
    expiry_date = (datetime.date.today() + datetime.timedelta(days=days)).isoformat()
    
    notion.pages.create(
        parent={"database_id": database_id},
        properties={
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
                # Cela capturera les erreurs d'authentification Gemini (Key not valid, etc.)
                st.error(f"Une erreur inattendue est survenue lors de l'analyse : {e}")

# Affichage et Validation (Le reste du code est inchangé)
if 'scanned_items' in st.session_state:
    st.subheader("Validation avant export vers Notion")
    
    category_options = ["Viande", "Légume", "Fruit", "Laitage", "Sec", "Autre"]

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
                 st.warning(f"{success_count} articles ajoutés. Vérifiez les avertissements ci-dessus pour les échecs.")
            
            st.session_state.pop('scanned_items', None)
            st.session_state.pop('validated_items', None)
