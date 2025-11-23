import streamlit as st
import datetime
import pandas as pd
import re

# --- Modules internes ---
from ia_utils import analyze_image
from notion_utils import (
    get_expiring_items,
    get_full_inventory,
    add_product_to_notion,
    export_menu_to_notion,
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

# CSS amélioré pour une meilleure mise en page
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

/* En-têtes un peu plus compactes */
h1, h2, h3 {
  margin-bottom: 0.3rem;
}

/* Style pour les cartes de menu */
.menu-card {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  border-radius: 15px;
  padding: 20px;
  margin: 15px 0;
  color: white;
  box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
}

.menu-card h3 {
  color: white;
  margin-top: 0;
  font-size: 1.3rem;
  border-bottom: 2px solid rgba(255, 255, 255, 0.3);
  padding-bottom: 10px;
  margin-bottom: 15px;
}

.meal-item {
  background: rgba(255, 255, 255, 0.15);
  border-radius: 10px;
  padding: 12px 15px;
  margin: 8px 0;
  backdrop-filter: blur(10px);
}

.meal-item strong {
  color: #ffd700;
  font-size: 1.05rem;
}

.meal-item p {
  margin: 5px 0 0 0;
  line-height: 1.5;
}

/* Style pour les badges de priorité */
.priority-badge {
  display: inline-block;
  padding: 4px 12px;
  border-radius: 20px;
  font-size: 0.85rem;
  font-weight: bold;
  margin-right: 8px;
}

.priority-1 {
  background: #e74c3c;
  color: white;
}

.priority-2 {
  background: #f39c12;
  color: white;
}

.priority-3 {
  background: #27ae60;
  color: white;
}

.shopping-item {
  background: #f8f9fa;
  border-left: 4px solid #667eea;
  padding: 12px 15px;
  margin: 8px 0;
  border-radius: 5px;
  display: flex;
  align-items: center;
  gap: 10px;
}

.shopping-item-dark {
  background: #2d3748;
  border-left: 4px solid #667eea;
  color: white;
}
</style>
""",
    unsafe_allow_html=True,
)

st.title("🍽️ Assistant Cuisine — Anti-Gaspi (Version Mobile)")


# ------------------------------------------------------------
# FONCTION POUR PARSER ET AFFICHER LE MENU
# ------------------------------------------------------------

def display_formatted_menu(menu_text):
    """Affiche le menu dans un format visuellement amélioré."""
    
    # Parser le menu par jour
    days = {}
    current_day = None
    
    lines = menu_text.strip().split("\n")
    for line in lines:
        line = line.strip()
        if not line:
            continue
            
        # Détecter un jour
        if re.match(r"^Jour\s+\d+", line, re.IGNORECASE):
            current_day = line
            days[current_day] = {"Petit-déjeuner": "", "Déjeuner": "", "Dîner": ""}
            continue
        
        if current_day:
            # Détecter les repas
            if "Petit-déjeuner" in line:
                days[current_day]["Petit-déjeuner"] = line.split(":", 1)[1].strip() if ":" in line else ""
            elif "Déjeuner" in line:
                days[current_day]["Déjeuner"] = line.split(":", 1)[1].strip() if ":" in line else ""
            elif "Dîner" in line:
                days[current_day]["Dîner"] = line.split(":", 1)[1].strip() if ":" in line else ""
    
    # Affichage avec des cartes stylisées
    for day, meals in days.items():
        st.markdown(f"""
        <div class="menu-card">
            <h3>📅 {day}</h3>
            <div class="meal-item">
                <strong>🌅 Petit-déjeuner</strong>
                <p>{meals.get('Petit-déjeuner', 'Non défini')}</p>
            </div>
            <div class="meal-item">
                <strong>☀️ Déjeuner</strong>
                <p>{meals.get('Déjeuner', 'Non défini')}</p>
            </div>
            <div class="meal-item">
                <strong>🌙 Dîner</strong>
                <p>{meals.get('Dîner', 'Non défini')}</p>
            </div>
        </div>
        """, unsafe_allow_html=True)


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
    st.subheader("📸 Scanner des aliments avec l'IA")
    st.caption(
        "Prends une photo de ton frigo, de tes produits ou de ton panier, "
        "choisis une IA, puis valide les aliments détectés."
    )

    ai_choice = st.selectbox(
        "Choix de l'IA pour l'analyse :",
        ["Gemini (Google)", "Claude (Anthropic)", "GPT-4 Vision (OpenAI)"],
        help="Tu peux changer d'IA si le résultat ne te convient pas.",
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
                st.rerun()


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
            st.rerun()


# ------------------------------------------------------------
# ONGLET 3 — INVENTAIRE / EXPIRATION
# ------------------------------------------------------------

with tab_inventory:
    st.subheader("🗃️ Inventaire & produits qui expirent bientôt")

    expiring = get_expiring_items()

    if expiring.empty:
        st.success("🎉 Aucun produit n'expire dans les 14 prochains jours.")
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
        with st.spinner("Analyse de l'inventaire et génération du menu…"):
            inventory = get_full_inventory()
            if inventory.empty:
                st.error(
                    "Impossible de générer un menu : inventaire vide ou aucun produit 'En stock'."
                )
            else:
                # Génération du menu avec l'IA (via menu_pro.generate_menu_ai)
                menu_text = generate_menu_ai(
                    inventory,
                    nb_days=nb_days,
                    nb_people=nb_people,
                    style=style_menu,
                    restrictions=restrictions,
                )

                st.markdown("---")
                st.subheader("📋 Menu généré")
                
                # Affichage formaté du menu
                display_formatted_menu(menu_text)

                # Liste de courses intelligente (priorisée)
                st.markdown("---")
                st.subheader("🛒 Liste de courses priorisée")

                missing_items = compute_missing_ingredients_pro(menu_text, inventory)

                if not missing_items:
                    st.success("🎉 Rien à acheter, tu as tout en stock pour ce menu !")
                else:
                    for it in missing_items:
                        prio = it.get("priorite", 3)
                        badge_class = f"priority-{prio}"
                        badge_text = "🔥 Urgent" if prio == 1 else ("⚠️ Important" if prio == 2 else "🟢 Normal")
                        
                        st.markdown(f"""
                        <div class="shopping-item">
                            <span class="priority-badge {badge_class}">{badge_text}</span>
                            <div>
                                <strong>{it['nom']}</strong> — {it['categorie']}<br>
                                <small>Pour {it['jour']} • {it['repas']}</small>
                            </div>
                        </div>
                        """, unsafe_allow_html=True)

                    st.markdown("---")
                    st.subheader("📄 Export PDF du menu")

                    # Bouton PDF premium (avec thème choisi dans la sidebar)
                    download_pdf_button(
                        menu_text,
                        missing_items,
                        logo_path=None,
                        theme=pdf_theme,
                    )

                    st.markdown("---")
                    st.subheader("📝 Export du menu vers Notion ('Menus')")

                    if st.button(
                        "📝 Exporter ce menu dans Notion",
                        use_container_width=True,
                    ):
                        try:
                            export_menu_to_notion(
                                menu_text,
                                missing_items,
                                nb_days,
                                nb_people,
                                style_menu,
                                restrictions,
                            )
                            st.success("✅ Menu exporté dans Notion (base 'Menus').")
                        except Exception as e:
                            st.error(f"Erreur lors de l'export Notion : {e}")


# ------------------------------------------------------------
# ONGLET 5 — RÉGLAGES / AIDE
# ------------------------------------------------------------

with tab_settings:
    st.subheader("⚙️ Réglages & Informations")

    st.markdown("### 🧩 Modules utilisés")
    st.markdown(
        """
- `ia_utils.py` → analyse d'images (Gemini / Claude / GPT-4o)
- `notion_utils.py` → connexion à ta base Notion (inventaire + menus)
- `menu_pro.py` → génération du menu & liste de courses intelligente
- `pdf_utils.py` → PDF premium (bandeau, QR, couleurs, urgences…)
"""
    )

    st.markdown("### 🎨 Thème PDF")
    st.write(f"Thème PDF actuel : **{pdf_theme}** (d'après ton choix dans la barre latérale).")

    st.markdown("### 🔑 Secrets nécessaires (Streamlit)")
    st.code(
        """
GEMINI_API_KEY
CLAUDE_API_KEY
OPENAI_API_KEY
NOTION_TOKEN
DATABASE_ID
MENU_DATABASE_ID
""",
        language="bash",
    )

    st.markdown("---")
    st.markdown("Merci d'utiliser l'Assistant Cuisine Anti-Gaspi 💚")
