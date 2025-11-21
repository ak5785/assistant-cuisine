import streamlit as st
from openai import OpenAI
from notion_client import Client
import datetime
import json

# --- CONFIGURATION ---
st.set_page_config(page_title="Assistant Cuisine", page_icon="🥦")

# Récupération des clés secrètes (depuis Streamlit Secrets)
try:
    openai_api_key = st.secrets["OPENAI_API_KEY"]
    notion_token = st.secrets["NOTION_TOKEN"]
    database_id = st.secrets["DATABASE_ID"]
except:
    st.error("Les clés API ne sont pas configurées dans Streamlit Cloud.")
    st.stop()

# Initialisation des clients
client_openai = OpenAI(api_key=openai_api_key)
notion = Client(auth=notion_token)

# Règles de conservation (Option B)
RULES = {
    "Viande": 2,
    "Légume": 5,
    "Fruit": 5,
    "Laitage": 7,
    "Sec": 365,
    "Autre": 3
}

def analyze_image(image_file):
    """Envoie l'image à GPT-4o pour analyse"""
    # Encodage de l'image (géré par OpenAI avec l'URL ou base64, ici via Streamlit nous utiliserons une description)
    # Note: Pour le MVP simple, GPT-4o via API supporte les images en base64.
    import base64
    
    bytes_data = image_file.getvalue()
    base64_image = base64.b64encode(bytes_data).decode('utf-8')

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
        model="gpt-4o-mini",
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
        max_tokens=500
    )
    
    content = response.choices[0].message.content
    # Nettoyage basique au cas où GPT mettrait des ```json
    content = content.replace("```json", "").replace("```", "").strip()
    return json.loads(content)

def add_to_notion(item):
    """Ajoute un élément validé dans Notion"""
    # Calcul de la date
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

# --- INTERFACE ---
st.title("📸 Scanner de Frigo")

uploaded_file = st.file_uploader("Prends une photo de tes courses", type=["jpg", "png", "jpeg"])

if uploaded_file:
    st.image(uploaded_file, caption="Image analysée", use_container_width=True)
    
    if st.button("🔍 Analyser avec l'IA"):
        with st.spinner("Analyse en cours..."):
            try:
                data = analyze_image(uploaded_file)
                st.session_state['scanned_items'] = data
                st.success(f"{len(data)} aliments détectés !")
            except Exception as e:
                st.error(f"Erreur d'analyse : {e}")

# Affichage et Validation
if 'scanned_items' in st.session_state:
    st.subheader("Validation avant export")
    
    # Formulaire pour valider
    with st.form("validation_form"):
        items_to_save = []
        for i, item in enumerate(st.session_state['scanned_items']):
            c1, c2, c3 = st.columns([2, 1, 1])
            with c1:
                name = st.text_input(f"Nom {i+1}", value=item['nom'], key=f"name_{i}")
            with c2:
                qty = st.text_input(f"Qté {i+1}", value=item['quantite'], key=f"qty_{i}")
            with c3:
                cat = st.selectbox(f"Catégorie {i+1}", ["Viande", "Légume", "Fruit", "Laitage", "Sec", "Autre"], index=["Viande", "Légume", "Fruit", "Laitage", "Sec", "Autre"].index(item['categorie']), key=f"cat_{i}")
            
            items_to_save.append({"nom": name, "quantite": qty, "categorie": cat})
        
        submitted = st.form_submit_button("✅ Valider et Envoyer vers Notion")
        
        if submitted:
            progress_bar = st.progress(0)
            for idx, item in enumerate(items_to_save):
                add_to_notion(item)
                progress_bar.progress((idx + 1) / len(items_to_save))
            
            st.success("Stock mis à jour dans Notion !")
            del st.session_state['scanned_items'] # Reset
