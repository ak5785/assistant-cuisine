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
    """Nettoie les ID Notion (peut être utile selon les formats)."""
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
#  1. AJOUT D’UN PRODUIT DANS L’INVENTAIRE
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
            parent={"database_id": format_id(DATABASE_ID)},
            properties={
                "Nom": {"title": [{"text": {"content": item["nom"]}}]},
                "Quantité": {"rich_text": [{"text": {"content": item["quantite"]}}]},
                "Catégorie": {"select": {"name": item["categorie"]}},
                "Délai": {"number": int(item["delai"])},
                "Date péremption": {"date": {"start": expiry_date.isoformat()}},
                "Status": {"select": {"name": "En stock"}},
            },
        )
    except Exception as e:
        raise Exception(f"Erreur lors de l’ajout Notion : {e}")


# ============================================================
#  2. RÉCUPÉRER L’INVENTAIRE COMPLET (STATUS = En stock)
# ============================================================

def get_full_inventory():
    if not DATABASE_ID:
        raise ValueError("DATABASE_ID manquant dans secrets.toml")

    try:
        response = notion.databases.query(
            database_id=format_id(DATABASE_ID),
            filter={"property": "Status", "select": {"equals": "En stock"}},
            sorts=[{"property": "Date péremption", "direction": "ascending"}],
        )
    except Exception as e:
        raise Exception(f"Erreur Notion lors de la récupération de l'inventaire : {e}")

    rows = []
    for p in response.get("results", []):
        props = p["properties"]

        nom = props["Nom"]["title"][0]["text"]["content"] if props["Nom"]["title"] else ""
        qte = props["Quantité"]["rich_text"][0]["text"]["content"] if props["Quantité"]["rich_text"] else ""
        cat = props["Catégorie"]["select"]["name"] if props["Catégorie"]["select"] else "Autre"
        delai = props["Délai"]["number"] if props["Délai"]["number"] else 0

        expiry_raw = props["Date péremption"]["date"]["start"] if props["Date péremption"]["date"] else None
        expiry_date = datetime.date.fromisoformat(expiry_raw) if expiry_raw else None

        days_left = (expiry_date - datetime.date.today()).days if expiry_date else 999

        rows.append(
            {
                "Nom": nom,
                "Quantité": qte,
                "Catégorie": cat,
                "Délai": delai,
                "Date péremption": expiry_date,
                "Jours Restants": days_left,
            }
        )

    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("Jours Restants")

    return df


# ============================================================
#  3. RÉCUPÉRER UNIQUEMENT LES PRODUITS QUI EXPIRENT SOUS 14 JOURS
# ============================================================

def get_expiring_items(days=14):
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
    - Date = aujourd’hui
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
            parent={"database_id": format_id(MENU_DATABASE_ID)},
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
        raise Exception(f"Erreur lors de l’export du menu dans Notion : {e}")
