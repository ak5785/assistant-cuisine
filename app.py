import streamlit as st
import datetime
import pandas as pd

# --- Modules internes ---
from ia_utils import analyze_image
from notion_utils import (
    get_expiring_items,
    get_full_inventory,
    add_product_to_notion,
    RULES,
)
from menu_pro import generate_menu_ai, compute_missing_ingredients_pro
from pdf_utils import download_pdf_button


# ------------------------------------------------------------
# CONFIG STREAMLIT
# ------------------------------------------------------------

st.set_page_config(
    page_title="Assistant Cuisine Anti-Gaspi",
    page_icon="🍽️",
    layout="wide",
)

# Un peu de CSS pour améliorer l’usage sur mobile
st.markdown(
    """
<style>
/* Réduire les marges sur mobile */
@media (max-width: 768px) {
  .block-container {
    padding-top: 0.5rem;
    padding-left: 0.6rem;
    padding-right: 0.6rem;
  }
}

/* Boutons plus larges et arrondis */
button[kind="primary"], button[kind="secondary"] {
  padding: 0.5rem 1.1rem;
  border-radius: 0.8rem !important;
  font-size: 0.95rem !important;
}

/* Petites cartes visuelles */
div.stContainer {
  border-radius: 0.9rem;
}

/* En-têtes un peu plus compactes */
h1, h2, h3 {
  margin-bottom: 0.3rem;
}
</style>
""",
    unsafe_allow_html=True,
)

st.title("🍽️ Assistant Cuisine — Anti-Gaspi (Version Mobile)")


# ------------------------------------------------------------
# SIDEBAR — OPTIONS GLOBALES (dont thème PDF)
# ------------------------------------------------------------

with st.sidebar:
    st.markdown("## ⚙️ Options globales")

    theme_choice = st.radio(
        "Thème du PDF",
        ["Auto", "Clair", "Sombre"],
        index=0,
        help="Thème utilisé pour le PDF généré. L'interface Streamlit suit les réglages Streamlit.",
    )

    # Pour le PDF : Auto = clair par défaut (Streamlit ne permet pas encore de lire le thème système)
    if theme_choice == "Sombre":
        pdf_theme = "dark"
    else:
        pdf_theme = "light"

    st.markdown("---")
    st.markdown(
        "💡 Utilise les onglets ci-dessous pour naviguer comme dans une app mobile."
    )


# ------------------------------------------------------------
# ONGLETS PRINCIPAUX (UX mobile)
# ------------------------------------------------------------

tab_scan, tab_manual, tab_inventory, tab_menu, tab_settings = st.tabs(
    ["📸 Scanner", "📝 Ajout manuel", "🗃️ Inventaire", "🍽️ Menu IA", "⚙️ Réglages"]
)


# ------------------------------------------------------------
# ONGLET 1 — SCANNER (PHOTO + IA)
# ------------------------------------------------------------

with tab_scan:
    st.subheader("📸 Scanner des aliments avec l’IA")
    st.caption(
        "Prends une photo de ton frigo, de tes produits ou de ton panier, "
        "choisis une IA, puis valide les aliments détectés."
    )

    ai_choice = st.selectbox(
        "Choix de l’IA pour l’analyse :",
        ["Gemini (Google)", "Claude (Anthropic)", "GPT-4 Vision (OpenAI)"],
        help="Tu peux changer d’IA si le résultat ne te convient pas.",
    )

    uploaded_file = st.file_uploader(
        "Télécharge une photo (jpg / jpeg / png)",
        type=["jpg", "jpeg", "png"],
    )

    if uploaded_file:
        st.image(uploaded_file, caption="Image chargée", use_container_width=True)

        if st.button("🔍 Analyser l'image", use_container_width=True):
            with st.spinner("Analyse IA en cours…"):
                try:
                    detected_items = analyze_image(uploaded_file, ai_choice)
                    st.session_state["detected_items"] = detected_items
                    st.success(f"{len(detected_items)} élément(s) reconnu(s) 🎉")
                except Exception as e:
                    st.error(f"Erreur IA : {e}")

    # Validation des éléments détectés (dans le même onglet)
    if "detected_items" in st.session_state:
        st.markdown("---")
        st.subheader("📝 Validation des aliments détectés")

        with st.form("validation_form"):
            items_to_add = []
            categories = list(RULES.keys())

            for i, item in enumerate(st.session_state["detected_items"]):
                c1, c2, c3 = st.columns([2, 1, 1])
                c4, c5 = st.columns([1, 1])

                # Nom
                with c1:
                    nom = st.text_input(
                        f"Nom #{i+1}",
                        item.get("nom", ""),
                        key=f"det_nom_{i}",
                    )

                # Quantité
                with c2:
                    qty = st.text_input(
                        f"Qté #{i+1}",
                        item.get("quantite", "1"),
                        key=f"det_qty_{i}",
                    )

                # Catégorie
                default_cat = item.get("categorie", "Autre")
                if default_cat not in categories:
                    default_cat = "Autre"
                with c3:
                    cat = st.selectbox(
                        f"Catégorie #{i+1}",
                        categories,
                        index=categories.index(default_cat),
                        key=f"det_cat_{i}",
                    )

                # Délai auto + modifiable
                auto_days = RULES.get(cat, 3)
                with c4:
                    delai = st.number_input(
                        f"Jours #{i+1}",
                        min_value=1,
                        max_value=30,
                        value=auto_days,
                        step=1,
                        key=f"det_delai_{i}",
                    )

                # Preview date
                with c5:
                    expiry = datetime.date.today() + datetime.timedelta(days=delai)
                    st.write(f"📅 {expiry.isoformat()}")

                items_to_add.append(
                    {
                        "nom": nom,
                        "quantite": qty,
                        "categorie": cat,
                        "delai": delai,
                    }
                )

            submitted = st.form_submit_button(
                "📤 Ajouter ces aliments dans Notion",
                use_container_width=True,
            )

            if submitted:
                nb_ok = 0
                for it in items_to_add:
                    try:
                        add_product_to_notion(it)
                        nb_ok += 1
                    except Exception as e:
                        st.error(f"Erreur lors de l'ajout : {e}")

                if nb_ok > 0:
                    st.success(f"✅ {nb_ok} aliment(s) ajouté(s) dans Notion.")
                    st.balloons()

                # Reset
                st.session_state.pop("detected_items", None)
                st.experimental_rerun()


# ------------------------------------------------------------
# ONGLET 2 — AJOUT MANUEL
# ------------------------------------------------------------

with tab_manual:
    st.subheader("📝 Ajouter manuellement des aliments")
    st.caption("Pratique si tu veux ajouter des produits sans photo.")

    if "manual_items" not in st.session_state:
        st.session_state.manual_items = [
            {"nom": "", "quantite": "1", "categorie": "Autre", "delai": 3}
        ]

    cols_top = st.columns([1, 1])
    with cols_top[0]:
        if st.button("➕ Ajouter une ligne", use_container_width=True):
            st.session_state.manual_items.append(
                {"nom": "", "quantite": "1", "categorie": "Autre", "delai": 3}
            )

    with st.form("manual_add_form"):
        updated = []
        categories = list(RULES.keys())

        for i, item in enumerate(st.session_state.manual_items):
            c1, c2, c3, c4, c5 = st.columns([2, 1, 1, 1, 1])

            with c1:
                nom = st.text_input(
                    f"Nom #{i+1}",
                    item["nom"],
                    key=f"m_nom_{i}",
                )
            with c2:
                qty = st.text_input(
                    f"Qté #{i+1}",
                    item["quantite"],
                    key=f"m_qty_{i}",
                )

            cat_value = item.get("categorie", "Autre")
            if cat_value not in categories:
                cat_value = "Autre"

            with c3:
                cat = st.selectbox(
                    f"Catégorie #{i+1}",
                    categories,
                    index=categories.index(cat_value),
                    key=f"m_cat_{i}",
                )

            with c4:
                delai = st.number_input(
                    f"Jours #{i+1}",
                    min_value=1,
                    max_value=30,
                    value=int(item.get("delai", RULES.get(cat, 3))),
                    step=1,
                    key=f"m_delai_{i}",
                )

            with c5:
                expiry = datetime.date.today() + datetime.timedelta(days=delai)
                st.write(f"📅 {expiry.isoformat()}")

            updated.append(
                {
                    "nom": nom,
                    "quantite": qty,
                    "categorie": cat,
                    "delai": delai,
                }
            )

        st.session_state.manual_items = updated

        submitted_manual = st.form_submit_button(
            "📤 Ajouter dans Notion",
            use_container_width=True,
        )

        if submitted_manual:
            nb_ok = 0
            for it in updated:
                try:
                    add_product_to_notion(it)
                    nb_ok += 1
                except Exception as e:
                    st.error(f"Erreur : {e}")

            if nb_ok > 0:
                st.success(f"✅ {nb_ok} aliment(s) ajouté(s) dans Notion.")
                st.balloons()

            st.session_state.manual_items = [
                {"nom": "", "quantite": "1", "categorie": "Autre", "delai": 3}
            ]
            st.experimental_rerun()


# ------------------------------------------------------------
# ONGLET 3 — INVENTAIRE / EXPIRATION
# ------------------------------------------------------------

with tab_inventory:
    st.subheader("🗃️ Inventaire & produits qui expirent bientôt")

    expiring = get_expiring_items()

    if expiring.empty:
        st.success("🎉 Aucun produit n’expire dans les 14 prochains jours.")
    else:
        st.caption("Produits à consommer en priorité :")
        st.dataframe(expiring, use_container_width=True)

    st.markdown("---")
    st.subheader("📦 Inventaire complet (En stock)")

    inv_df = get_full_inventory()
    if inv_df.empty:
        st.info("Aucun produit 'En stock' trouvé dans Notion.")
    else:
        st.dataframe(inv_df, use_container_width=True)


# ------------------------------------------------------------
# ONGLET 4 — MENU INTELLIGENT IA
# ------------------------------------------------------------

with tab_menu:
    st.subheader("🍽️ Menu intelligent anti-gaspi (IA)")
    st.caption(
        "Génère un menu complet sur plusieurs jours, basé sur ton inventaire, "
        "en priorisant les aliments à consommer."
    )

    nb_days = st.slider("Durée du menu (jours)", 3, 7, 5)
    nb_people = st.number_input("Nombre de personnes", 1, 10, 2)
    style_menu = st.selectbox(
        "Style du menu",
        ["Équilibré", "Rapide", "Économique", "Gourmand", "Healthy", "Végétarien"],
    )
    restrictions = st.text_input(
        "Restrictions alimentaires (optionnel)",
        placeholder="ex : sans porc, sans lactose, végétarien…",
    )

    if st.button("🍽️ Générer le menu intelligent", use_container_width=True):
        with st.spinner("Analyse de l’inventaire et génération du menu…"):
            inventory = get_full_inventory()
            if inventory.empty:
                st.error(
                    "Impossible de générer un menu : inventaire vide ou aucun produit 'En stock'."
                )
            else:
                # Génération du menu avec l’IA (via menu_pro.generate_menu_ai)
                menu_text = generate_menu_ai(
                    inventory,
                    nb_days=nb_days,
                    nb_people=nb_people,
                    style=style_menu,
                    restrictions=restrictions,
                )

                st.markdown("---")
                st.subheader("📋 Menu généré")
                st.markdown(menu_text)

                # Liste de courses intelligente (priorisée)
                st.markdown("---")
                st.subheader("🛒 Liste de courses priorisée")

                missing_items = compute_missing_ingredients_pro(menu_text, inventory)

                if not missing_items:
                    st.success("🎉 Rien à acheter, tu as tout en stock pour ce menu !")
                else:
                    for it in missing_items:
                        badge = (
                            "🔥"
                            if it["priorite"] == 1
                            else ("⚠️" if it["priorite"] == 2 else "🟢")
                        )
                        line = (
                            f"{badge} {it['nom']} — {it['categorie']} — "
                            f"{it['jour']} / {it['repas']}"
                        )
                        if it.get("quantite_estimee"):
                            line += f" (~{it['quantite_estimee']})"
                        st.write("- " + line)

                    st.markdown("---")
                    st.subheader("📄 Export PDF du menu")

                    # Bouton PDF premium (avec thème choisi dans la sidebar)
                    download_pdf_button(
                        menu_text,
                        missing_items,
                        logo_path=None,
                        theme=pdf_theme,
                    )


# ------------------------------------------------------------
# ONGLET 5 — RÉGLAGES / AIDE
# ------------------------------------------------------------

with tab_settings:
    st.subheader("⚙️ Réglages & Informations")

    st.markdown("### 🧩 Modules utilisés")
    st.markdown(
        """
- `ia_utils.py` → analyse d’images (Gemini / Claude / GPT-4o)
- `notion_utils.py` → connexion à ta base Notion (inventaire)
- `menu_pro.py` → génération du menu & liste de courses intelligente
- `pdf_utils.py` → PDF premium (bandeau, QR, couleurs, urgences…)
"""
    )

    st.markdown("### 🎨 Thème PDF")
    st.write(f"Thème PDF actuel : **{pdf_theme}** (d’après ton choix dans la barre latérale).")

    st.markdown("### 🔑 Secrets nécessaires (Streamlit)")
    st.code(
        """
GEMINI_API_KEY
CLAUDE_API_KEY
OPENAI_API_KEY
NOTION_TOKEN
DATABASE_ID
""",
        language="bash",
    )

    st.markdown("---")
    st.markdown("Merci d’utiliser l’Assistant Cuisine Anti-Gaspi 💚")
