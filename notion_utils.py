import streamlit as st
import datetime
import pandas as pd
from notion_client import Client


# ------------------------------------------------------------
# 1. VARIABLES GLOBALes & CONFIGURATION
# ------------------------------------------------------------

NOTION_TOKEN = st.secrets["NOTION_TOKEN"]
DATABASE_ID = st.secrets["DATABASE_ID"]

notion = Client(auth=NOTION_TOKEN)

# Règles de durée par défaut pour chaque catégorie
RULES = {
    "Viande": 2,
    "Volaille": 2,
    "Poisson": 1,
    "Légume": 5,
    "Fruit": 5,
    "Laitage": 7,
    "Produit laitier": 7,
    "Sec": 365,
    "Pâtisserie": 3,
    "Boulangerie": 2,
    "Plat préparé": 4,
    "Autre": 3
}


# ------------------------------------------------------------
# 2. FORMATAGE DE L'ID NOTION
# ------------------------------------------------------------

def format_id(db_id: str):
    """Retire les tirets, car Notion accepte les deux formats."""
    return db_id.replace("-", "").strip()


# ------------------------------------------------------------
# 3. AJOUT D'UN PRODUIT DANS NOTION
# ------------------------------------------------------------

def add_product_to_notion(item: dict):
    """
    item = {
        'nom': 'Tomate',
        'quantite': '3',
        'categorie': 'Légume',
        'delai': 5
    }
    """

    name = item["nom"]
    qty = item["quantite"]
    cat = item["categorie"]
    delai = item["delai"]

    expiry = (datetime.date.today() + datetime.timedelta(days=delai)).isoformat()

    try:
        notion.pages.create(
            parent={"database_id": format_id(DATABASE_ID)},
            properties={
                "Nom": {"title": [{"text": {"content": name}}]},
                "Quantité": {"rich_text": [{"text": {"content": qty}}]},
                "Catégorie": {"select": {"name": cat}},
                "Statut": {"select": {"name": "En stock"}},
                "Délai (jours)": {"number": delai},
                "Date_Péremption": {"date": {"start": expiry}}
            }
        )

    except Exception as e:
        raise Exception(f"Erreur lors de l’ajout à Notion : {e}")


# ------------------------------------------------------------
# 4. RÉCUPÉRATION INVENTAIRE COMPLET
# ------------------------------------------------------------

def get_full_inventory():
    """
    Retourne tous les produits en stock sous forme de pandas.DataFrame,
    avec colonnes :
    - Nom
    - Quantité
    - Catégorie
    - Date_Péremption
    - Jours Restants
    """

    try:
        res = notion.databases.query(
            database_id=format_id(DATABASE_ID),
            filter={
                "property": "Statut",
                "select": {"equals": "En stock"}
            }
        )
    except Exception as e:
        st.error(f"Erreur Notion : {e}")
        return pd.DataFrame()

    today = datetime.date.today()
    items = []

    for page in res["results"]:
        props = page["properties"]

        name = props["Nom"]["title"][0]["plain_text"] if props["Nom"]["title"] else "Sans nom"
        qty = props["Quantité"]["rich_text"][0]["plain_text"] if props["Quantité"]["rich_text"] else "1"
        cat = props["Catégorie"]["select"]["name"] if props["Catégorie"]["select"] else "Autre"

        expiry_raw = props.get("Date_Péremption", {}).get("date", {}).get("start", None)

        if expiry_raw:
            expiry = datetime.date.fromisoformat(expiry_raw)
            days_left = (expiry - today).days
        else:
            expiry = None
            days_left = None

        items.append({
            "Nom": name,
            "Quantité": qty,
            "Catégorie": cat,
            "Date_Péremption": expiry_raw,
            "Jours Restants": days_left
        })

    df = pd.DataFrame(items)

    if not df.empty:
        df = df.sort_values("Jours Restants", na_position="last")

    return df


# ------------------------------------------------------------
# 5. PRODUITS EXPIRANT BIENTÔT (PAR DÉFAUT 14 JOURS)
# ------------------------------------------------------------

def get_expiring_items(days_threshold=14):
    """
    Récupère les produits dont la date est <= aujourd’hui + X jours.
    Retourne un DataFrame.
    """

    limit_date = (datetime.date.today() + datetime.timedelta(days=days_threshold)).isoformat()

    try:
        res = notion.databases.query(
            database_id=format_id(DATABASE_ID),
            filter={
                "and": [
                    {"property": "Statut", "select": {"equals": "En stock"}},
                    {"property": "Date_Péremption", "date": {"on_or_before": limit_date}}
                ]
            }
        )
    except Exception as e:
        st.error(f"Erreur Notion : {e}")
        return pd.DataFrame()

    today = datetime.date.today()
    items = []

    for page in res["results"]:
        props = page["properties"]

        name = props["Nom"]["title"][0]["plain_text"] if props["Nom"]["title"] else "Sans nom"
        qty = props["Quantité"]["rich_text"][0]["plain_text"] if props["Quantité"]["rich_text"] else "1"
        cat = props["Catégorie"]["select"]["name"] if props["Catégorie"]["select"] else "Autre"

        expiry_raw = props.get("Date_Péremption", {}).get("date", {}).get("start", None)
        if expiry_raw:
            expiry = datetime.date.fromisoformat(expiry_raw)
            days_left = (expiry - today).days
        else:
            days_left = None

        items.append({
            "Nom": name,
            "Quantité": qty,
            "Catégorie": cat,
            "Date_Péremption": expiry_raw,
            "Jours Restants": days_left
        })

    df = pd.DataFrame(items)
    if not df.empty:
        df = df.sort_values("Jours Restants", na_position="last")

    return df
