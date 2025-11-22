import streamlit as st
import datetime
import pandas as pd
from notion_client import Client

# ============================================================
#  CLIENT NOTION
# ============================================================

NOTION_TOKEN = st.secrets.get("NOTION_TOKEN", None)
DATABASE_ID = st.secrets.get("DATABASE_ID", None)           # Inventaire
MENU_DATABASE_ID = st.secrets.get("MENU_DATABASE_ID", None) # Base Menus

if NOTION_TOKEN:
    notion = Client(auth=NOTION_TOKEN)
else:
    raise ValueError("❌ NOTION_TOKEN manquant dans secrets.toml")


# ============================================================
#  UTILITAIRES
# ============================================================

def format_id(id_raw):
    """Nettoie les ID Notion (enlève les tirets si présents)."""
    if not id_raw:
        return id_raw
    return id_raw.replace("-", "")


# ============================================================
#  RÈGLES PAR CATÉGORIE (pour délai auto)
# ============================================================

RULES = {
    "Viande": 2,
    "Poisson": 1,
    "Fruit": 4,
    "Légume": 4,
    "Féculent": 6,
    "Produit laitier": 3,
    "Condiment": 30,
    "Autre": 5,
}


# ============================================================
#  1. AJOUT D'UN PRODUIT DANS L'INVENTAIRE
# ============================================================

def add_product_to_notion(item):
    """
    item = {
      "nom": "...",
      "quantite": "...",
      "categorie": "...",
      "delai": int
    }
    """

    if not DATABASE_ID:
        raise ValueError("DATABASE_ID manquant dans secrets.toml")

    expiry_date = datetime.date.today() + datetime.timedelta(days=int(item["delai"]))

    try:
        notion.pages.create(
            parent={"database_id": DATABASE_ID},
            properties={
                "Nom": {"title": [{"text": {"content": item["nom"]}}]},
                "Quantité": {"rich_text": [{"text": {"content": item["quantite"]}}]},
                "Catégorie": {"select": {"name": item["categorie"]}},
                "Délai": {"number": int(item["delai"])},
                "Date péremption": {"date": {"start": expiry_date.isoformat()}},
                "Statut": {"select": {"name": "En stock"}},
            },
        )
    except Exception as e:
        raise Exception(f"Erreur lors de l'ajout Notion : {e}")


# ============================================================
#  2. RÉCUPÉRER L'INVENTAIRE COMPLET (STATUT = En stock)
# ============================================================

def get_full_inventory():
    """Récupère tous les produits avec le statut 'En stock'."""
    if not DATABASE_ID:
        st.warning("DATABASE_ID manquant dans secrets.toml")
        return pd.DataFrame()

    try:
        # Requête Notion avec gestion des différents noms de propriété possibles
        response = notion.databases.query(
            database_id=DATABASE_ID,
            filter={
                "or": [
                    {"property": "Statut", "select": {"equals": "En stock"}},
                    {"property": "Status", "select": {"equals": "En stock"}}
                ]
            },
            sorts=[{"property": "Date péremption", "direction": "ascending"}],
        )
    except Exception as e:
        st.error(f"Erreur lors de la connexion à Notion : {e}")
        st.info("Vérifiez que votre base de données Notion contient bien les propriétés : Nom, Quantité, Catégorie, Délai, Date péremption, et Statut (ou Status)")
        return pd.DataFrame()

    rows = []
    for p in response.get("results", []):
        props = p["properties"]

        # Extraction sécurisée des propriétés
        try:
            nom = props["Nom"]["title"][0]["text"]["content"] if props.get("Nom", {}).get("title") else ""
            qte = props["Quantité"]["rich_text"][0]["text"]["content"] if props.get("Quantité", {}).get("rich_text") else ""
            
            # Gestion de la catégorie
            cat_prop = props.get("Catégorie", {})
            cat = cat_prop.get("select", {}).get("name", "Autre") if cat_prop.get("select") else "Autre"
            
            # Gestion du délai
            delai = props.get("Délai", {}).get("number", 0) or 0

            # Gestion de la date de péremption
            expiry_raw = None
            date_prop = props.get("Date péremption", {})
            if date_prop and date_prop.get("date"):
                expiry_raw = date_prop["date"].get("start")
            
            expiry_date = datetime.date.fromisoformat(expiry_raw) if expiry_raw else None
            days_left = (expiry_date - datetime.date.today()).days if expiry_date else 999

            rows.append({
                "Nom": nom,
                "Quantité": qte,
                "Catégorie": cat,
                "Délai": delai,
                "Date péremption": expiry_date,
                "Jours Restants": days_left,
            })
        except Exception as e:
            st.warning(f"Erreur lors du traitement d'un produit : {e}")
            continue

    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("Jours Restants")

    return df


# ============================================================
#  3. RÉCUPÉRER UNIQUEMENT LES PRODUITS QUI EXPIRENT SOUS 14 JOURS
# ============================================================

def get_expiring_items(days=14):
    """Retourne les produits qui expirent dans les X jours."""
    inv = get_full_inventory()

    if inv.empty:
        return pd.DataFrame()

    soon = inv[inv["Jours Restants"] <= days]
    return soon.sort_values("Jours Restants")


# ============================================================
#  4. EXPORT DU MENU COMPLET DANS NOTION (base "Menus")
# ============================================================

def export_menu_to_notion(menu_text, missing_items, nb_days, nb_people, style_menu, restrictions):
    """
    Crée une page dans une base Notion 'Menus' avec :
    - Nom = Menu Semaine XX - 2025
    - Semaine = Semaine XX - 2025
    - Date = aujourd'hui
    - Menu = texte
    - Courses = texte
    - Résumé = infos
    """

    if not MENU_DATABASE_ID:
        raise ValueError("MENU_DATABASE_ID manquant dans secrets.toml")

    today = datetime.date.today()
    week_num = today.isocalendar()[1]
    sem_label = f"Semaine {week_num} - {today.year}"

    title = f"Menu {sem_label}"
    resume = f"Menu {nb_days} jours • {nb_people} pers • Style : {style_menu}"

    # Liste de courses priorisée
    if not missing_items:
        courses_text = "Aucun ingrédient manquant, tout est déjà en stock 👍"
    else:
        lines = []
        for it in missing_items:
            prio = it.get("priorite", 3)
            badge = "🔥P1" if prio == 1 else ("⚠️P2" if prio == 2 else "🟢P3")
            line = f"{badge} — {it['nom']} — {it['categorie']} — {it['jour']} / {it['repas']}"
            if it.get("quantite_estimee"):
                line += f" (~{it['quantite_estimee']})"
            lines.append(line)
        courses_text = "\n".join(lines)

    try:
        notion.pages.create(
            parent={"database_id": MENU_DATABASE_ID},
            properties={
                "Nom": {"title": [{"text": {"content": title}}]},
                "Semaine": {"rich_text": [{"text": {"content": sem_label}}]},
                "Date": {"date": {"start": today.isoformat()}},
                "Menu": {"rich_text": [{"text": {"content": menu_text[:1900]}}]},
                "Courses": {"rich_text": [{"text": {"content": courses_text[:1900]}}]},
                "Résumé": {"rich_text": [{"text": {"content": resume}}]},
            },
        )
    except Exception as e:
        raise Exception(f"Erreur lors de l'export du menu dans Notion : {e}")