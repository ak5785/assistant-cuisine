import streamlit as st
import datetime
import pandas as pd

# --- Import modules ---
from ia_utils import analyze_image
from notion_utils import (
    get_expiring_items,
    get_full_inventory,
    add_product_to_notion,
    RULES
)
from menu_pro import generate_menu_ai, compute_missing_ingredients_pro
from pdf_utils import download_pdf_button


# ------------------------------------------------------------
# CONFIG STREAMLIT
# ------------------------------------------------------------

st.set_page_config(
    page_title="Assistant Cuisine Anti-Gaspi",
    page_icon="🍽️",
    layout="wide"
)

st.title("🍽️ Assistant Cuisine — Anti-Gaspi (Version Premium)")


# ------------------------------------------------------------
# SECTION 1 — SCAN PHOTO VIA IA
# ------------------------------------------------------------

st.header("📸 Ajouter des aliments via une photo")

ai_choice = st.selectbox(
    "Choix de l'IA pour l’analyse :",
    ["Gemini (Google)", "Claude (Anthropic)", "GPT-4 Vision (OpenAI)"]
)

uploaded_file = st.file_uploader("Télécharge une photo", type=["jpg", "jpeg", "png"])

if uploaded_file:
    st.image(uploaded_file, caption="Image chargée", use_container_width=True)

    if st.button("🔍 Analyser l'image"):
        with st.spinner("Analyse IA en cours…"):
            try:
                detected_items = analyze_image(uploaded_file, ai_choice)
                st.success(f"{len(detected_items)} élément(s) trouvé(s)")
                st.session_state["detected_items"] = detected_items
            except Exception as e:
                st.error(f"Erreur IA : {e}")


# ------------------------------------------------------------
# SECTION 2 — VALIDATION & AJOUT DES PRODUITS
# ------------------------------------------------------------

if "detected_items" in st.session_state:

    st.subheader("📝 Validation des aliments détectés")

    with st.form("validation_form"):
        items_to_add = []

        for i, item in enumerate(st.session_state["detected_items"]):
            c1, c2, c3, c4, c5 = st.columns([2, 1, 1, 1, 1])

            with c1:
                nom = st.text_input(f"Nom #{i+1}", item.get("nom", ""), key=f"nom_{i}")

            with c2:
                qty = st.text_input(f"Qté #{i+1}", item.get("quantite", "1"), key=f"qty_{i}")

            with c3:
                cat = st.selectbox(f"Catégorie #{i+1}", list(RULES.keys()),
                                   index=list(RULES.keys()).index(item.get("categorie", "Autre")),
                                   key=f"cat_{i}")

            auto_days = RULES.get(cat, 3)

            with c4:
                delai = st.number_input(
                    f"Jours #{i+1}",
                    min_value=1, max_value=30,
                    value=auto_days,
                    key=f"delai_{i}"
                )

            with c5:
                expiry = (datetime.date.today() + datetime.timedelta(days=delai))
                st.write(f"📅 {expiry}")

            items_to_add.append({
                "nom": nom,
                "quantite": qty,
                "categorie": cat,
                "delai": delai
            })

        submitted = st.form_submit_button("📤 Ajouter à Notion")

        if submitted:
            count = 0
            for it in items_to_add:
                try:
                    add_product_to_notion(it)
                    count += 1
                except Exception as e:
                    st.error(f"❌ Erreur : {e}")

            st.success(f"✅ {count} produit(s) ajouté(s)")
            st.session_state.pop("detected_items", None)
            st.rerun()


# ------------------------------------------------------------
# SECTION 3 — AJOUT MANUEL
# ------------------------------------------------------------

st.header("✏️ Ajouter manuellement des aliments")

if "manual_items" not in st.session_state:
    st.session_state.manual_items = [{
        "nom": "", "quantite": "1", "categorie": "Autre", "delai": 3
    }]

if st.button("➕ Ajouter une ligne"):
    st.session_state.manual_items.append({
        "nom": "", "quantite": "1", "categorie": "Autre", "delai": 3
    })

with st.form("manual_add_form"):
    updated = []

    for i, item in enumerate(st.session_state.manual_items):
        c1, c2, c3, c4, c5 = st.columns([2, 1, 1, 1, 1])

        with c1:
            nom = st.text_input(f"Nom #{i+1}", item["nom"], key=f"m_nom_{i}")

        with c2:
            qty = st.text_input(f"Qté #{i+1}", item["quantite"], key=f"m_qty_{i}")

        with c3:
            cat = st.selectbox(f"Catégorie #{i+1}", list(RULES.keys()),
                               index=list(RULES.keys()).index(item["categorie"]),
                               key=f"m_cat_{i}")

        auto_days = RULES.get(cat, 3)

        with c4:
            delai = st.number_input(f"Jours #{i+1}", min_value=1, max_value=30,
                                    value=item["delai"], key=f"m_delai_{i}")

        with c5:
            expiry = datetime.date.today() + datetime.timedelta(days=delai)
            st.write(f"📅 {expiry}")

        updated.append({"nom": nom, "quantite": qty, "categorie": cat, "delai": delai})

    st.session_state.manual_items = updated

    add_manual = st.form_submit_button("📤 Ajouter dans Notion")

    if add_manual:
        count = 0
        for it in updated:
            try:
                add_product_to_notion(it)
                count += 1
            except Exception as e:
                st.error(f"Erreur : {e}")

        st.success(f"{count} produit(s) ajouté(s) dans Notion")
        st.session_state.manual_items = [{
            "nom": "", "quantite": "1", "categorie": "Autre", "delai": 3
        }]
        st.rerun()


# ------------------------------------------------------------
# SECTION 4 — INVENTAIRE & EXPIRATION
# ------------------------------------------------------------

st.header("🧊 Produits qui expirent bientôt")

df_expiring = get_expiring_items()

if df_expiring.empty:
    st.success("🎉 Aucun produit n’expire dans les 14 prochains jours.")
else:
    st.dataframe(df_expiring, use_container_width=True)


# ------------------------------------------------------------
# SECTION 5 — MENU INTELLIGENT (Premium)
# ------------------------------------------------------------

st.header("🧠 Menu intelligent Anti-Gaspi (Premium)")

nb_days = st.slider("Durée du menu (jours)", 3, 7, 5)
nb_people = st.number_input("Nombre de personnes", 1, 10, 2)
style_menu = st.selectbox("Style du menu", ["Équilibré", "Rapide", "Économique", "Gourmand", "Healthy", "Végétarien"])
restrictions = st.text_input("Restrictions alimentaires (optionnel)")

if st.button("🍽️ Générer le menu intelligent"):
    with st.spinner("Création du menu par l’IA…"):
        inventory = get_full_inventory()

        menu_text = generate_menu_ai(
            inventory,
            nb_days=nb_days,
            nb_people=nb_people,
            style=style_menu,
            restrictions=restrictions
        )

        st.subheader("📋 Menu généré")
        st.markdown(menu_text)

        # Liste de courses intelligente
        st.subheader("🛒 Liste de courses priorisée (Premium)")
        missing_items = compute_missing_ingredients_pro(menu_text, inventory)

        if not missing_items:
            st.success("🎉 Rien à acheter !")
        else:
            for it in missing_items:
                st.write(f"- P{it['priorite']} — {it['nom']} ({it['categorie']}) [{it['jour']}]")

        # Bouton PDF premium+
        download_pdf_button(menu_text, missing_items)

