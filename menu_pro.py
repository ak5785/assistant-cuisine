import re
import streamlit as st
import requests
from google import genai
from google.genai import types

# ============================================================
#  GÉNÉRATION IA STABLE (Gemini → fallback GPT)
# ============================================================

def gemini_generate_text(prompt: str) -> str:
    """Appel Gemini en mode TEXTE uniquement (stable)."""
    GEMINI_KEY = st.secrets.get("GEMINI_API_KEY")
    if not GEMINI_KEY:
        raise ValueError("GEMINI_API_KEY manquante dans secrets.toml")

    client = genai.Client(api_key=GEMINI_KEY)

    try:
        response = client.models.generate_content(
            model="gemini-2.0-flash-exp",
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.35,
            )
        )
        return response.text.strip()
    except Exception as e:
        raise Exception(f"Erreur Gemini texte : {e}")


def gpt_generate_text(prompt: str) -> str:
    """Fallback OpenAI GPT-4o-mini."""
    OPENAI_KEY = st.secrets.get("OPENAI_API_KEY")
    if not OPENAI_KEY:
        raise ValueError("OPENAI_API_KEY manquante dans secrets.toml")

    headers = {
        "Authorization": f"Bearer {OPENAI_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": "gpt-4o-mini",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 2000,
        "temperature": 0.35
    }

    res = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers=headers,
        json=payload
    )

    if res.status_code != 200:
        raise Exception("Erreur OpenAI : " + res.text)

    return res.json()["choices"][0]["message"]["content"].strip()


# ============================================================
#  GÉNÉRATION DE MENU IA STABLE
# ============================================================

def generate_menu_ai(inventory_df, nb_days=5, nb_people=2, style="Équilibré", restrictions=""):
    """Génère un menu texte stable, formaté, exploitable par parsing."""
    
    # Trier par jours restants
    inv = inventory_df.sort_values("Jours Restants", ascending=True)

    expiring_soon_list = inv[inv["Jours Restants"] <= 3]["Nom"].tolist()
    full_stock_list = inv["Nom"].tolist()

    expiring_soon = ", ".join(expiring_soon_list) if expiring_soon_list else "aucun"
    full_stock = ", ".join(full_stock_list) if full_stock_list else "aucun"

    prompt = f"""
Tu es un chef spécialisé en anti-gaspillage.

Génère un menu sur {nb_days} jours pour {nb_people} personnes.
Style demandé : {style}
Restrictions : {restrictions if restrictions else "aucune"}

ALIMENTS EN STOCK :
{full_stock}

ALIMENTS À CONSOMMER EN URGENCE :
{expiring_soon}

CONTRAINTES :
- 3 repas par jour : Petit-déjeuner, Déjeuner, Dîner
- Utilise en priorité les aliments proches d'expiration
- Utilise le stock existant autant que possible
- Tu peux ajouter des ingrédients secondaires (épices, condiments)
- Format strict demandé :

Jour 1
  Petit-déjeuner : ...
  Déjeuner : ...
  Dîner : ...

Jour 2
  Petit-déjeuner : ...
  Déjeuner : ...
  Dîner : ...

…

NE RAJOUTE AUCUN TEXTE AVANT OU APRÈS.
PAS DE TITRES.
PAS DE JSON.
PAS DE MARKDOWN.
    """

    # 1) Gemini
    try:
        out = gemini_generate_text(prompt)
        if out.lower().startswith("jour"):
            return out
        st.warning("Format Gemini inattendu → tentative GPT…")
    except Exception as e:
        st.warning(f"Gemini erreur : {e} → tentative GPT…")

    # 2) GPT fallback
    out = gpt_generate_text(prompt)
    if out.lower().startswith("jour"):
        return out

    return "Erreur IA : impossible de générer un menu valide."


# ============================================================
#  PARSING DU MENU (Jour → repas)
# ============================================================

def parse_menu_structure(menu_text):
    """
    Transforme le texte du menu en structure exploitable :
    {
      "Jour 1": {
         "Petit-déjeuner": "...",
         "Déjeuner": "...",
         "Dîner": "..."
      },
      ...
    }
    """
    days = {}
    current_day = None

    lines = menu_text.split("\n")
    for line in lines:
        line = line.strip()

        # Détecter un "Jour X"
        if re.match(r"^Jour\s+\d+", line, re.IGNORECASE):
            current_day = line
            days[current_day] = {}
            continue

        # Repas
        if "Petit-déjeuner" in line:
            days[current_day]["Petit-déjeuner"] = line.split(":", 1)[1].strip()
        elif "Déjeuner" in line:
            days[current_day]["Déjeuner"] = line.split(":", 1)[1].strip()
        elif "Dîner" in line:
            days[current_day]["Dîner"] = line.split(":", 1)[1].strip()

    return days


# ============================================================
#  EXTRACTION DES INGREDIENTS D’UNE PHRASE
# ============================================================

# Liste générale d'ingrédients secondaires qu’on ignore s’ils manquent
INGREDIENTS_SECONDAIRES = [
    "sel", "poivre", "huile", "vinaigre", "beurre", "épice", "épices",
    "ail", "oignon", "herbe", "herbes", "bouillon", "levure",
    "sucre", "citron", "miel", "sauce", "condiment"
]

def extract_ingredients_from_text(text):
    """Extraction simple des mots-clés alimentaires."""
    text = text.lower()

    # Remplacement ponctuation → espaces
    text = re.sub(r"[.,;:!?()]", " ", text)

    tokens = text.split()
    ingredients = set()

    for tok in tokens:
        if len(tok) < 3:
            continue
        if tok in INGREDIENTS_SECONDAIRES:
            continue
        ingredients.add(tok)

    return ingredients


# ============================================================
#  CALCUL DES MANQUANTS (PRO VERSION)
# ============================================================

def compute_missing_ingredients_pro(menu_text, inventory_df):
    """
    Compare chaque repas du menu avec l’inventaire,
    renvoie une liste :
      [
        {
          "nom": "...",
          "categorie": "...",
          "priorite": 1/2/3,
          "jour": "...",
          "repas": "...",
          "quantite_estimee": "..."
        }
      ]
    """

    parsed = parse_menu_structure(menu_text)
    inv_names = [n.lower() for n in inventory_df["Nom"].tolist()]

    results = []

    for day, meals in parsed.items():
        for repas, description in meals.items():
            needed = extract_ingredients_from_text(description)

            for ing in needed:
                # déjà en stock ?
                if ing in inv_names:
                    continue

                # secondaire → on ignore
                if ing in INGREDIENTS_SECONDAIRES:
                    continue

                # Création entrée manquante
                result = {
                    "nom": ing,
                    "categorie": "Ingrédient",
                    "jour": day,
                    "repas": repas,
                    "priorite": 3,
                    "quantite_estimee": None
                }

                # priorisation (ex: premier jour = priorité haute)
                day_num = int(re.findall(r"\d+", day)[0])
                if day_num == 1:
                    result["priorite"] = 1
                elif day_num == 2:
                    result["priorite"] = 2

                results.append(result)

    return results
