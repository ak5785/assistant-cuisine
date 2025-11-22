import re
from typing import List, Dict


# ------------------------------------------------------------
# 1) Catégories automatiques (intelligence simple & robuste)
# ------------------------------------------------------------

CATEGORY_KEYWORDS = {
    "viande": ["boeuf", "bœuf", "poulet", "porc", "veau", "agneau", "jambon", "lardon", "saucisse"],
    "poisson": ["saumon", "thon", "cabillaud", "merlu", "colin", "truite", "crevette"],
    "féculent": ["pâtes", "pates", "riz", "semoule", "quinoa", "couscous", "pommes de terre", "pomme de terre", "patate"],
    "légume": ["carotte", "carottes", "courgette", "courgettes", "poivron", "oignon", "tomate", "brocoli", "salade", "épinard", "haricot", "chou", "champignon"],
    "fruit": ["pomme", "banane", "poire", "kiwi", "orange", "mandarine", "fraise", "raisin"],
    "laitier": ["lait", "yaourt", "fromage", "crème", "beurre", "mozzarella", "gruyère", "cheddar"],
}


def categorize_ingredient(name: str) -> str:
    """
    Détecte la catégorie d’un ingrédient selon des mots-clés.
    """
    n = name.lower()
    for cat, keywords in CATEGORY_KEYWORDS.items():
        for kw in keywords:
            if kw in n:
                return cat
    return "autre"


# ------------------------------------------------------------
# 2) Extraction du plan (jours / repas / textes)
# ------------------------------------------------------------

def parse_menu_structure(menu_text: str) -> List[Dict]:
    """
    Analyse le menu IA et construit une liste structurée :
    [
        { "day": "Jour 1", "meal": "Déjeuner", "text": "Poulet + riz" },
        ...
    ]
    """
    lines = menu_text.split("\n")
    blocks = []
    current_day = None
    current_meal = None

    for line in lines:
        l = line.strip()
        lower = l.lower()

        # Détection jour
        if lower.startswith("jour"):
            current_day = l
            current_meal = None
            continue

        # Détection repas
        if any(k in lower for k in ["petit", "déj", "dejeuner", "dîner", "diner", "collation", "snack"]):
            current_meal = l
            continue

        # Ingrédient / description associée
        if current_day and current_meal and l:
            blocks.append({
                "day": current_day,
                "meal": current_meal,
                "text": l
            })

    return blocks


# ------------------------------------------------------------
# 3) Extraction des ingrédients du texte IA
# ------------------------------------------------------------

def extract_ingredients_from_text(text: str) -> List[str]:
    """
    Sépare un texte brut en ingrédients probables.
    """
    t = text.lower()
    t = re.sub(r"[•\-•\t]", " ", t)
    parts = re.split(r",| avec | et ", t)

    ingredients = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if any(w in p for w in ["cuire", "four", "mixer", "ajouter", "servir"]):
            continue
        ingredients.append(p)

    return ingredients


# ------------------------------------------------------------
# 4) Estimation des quantités (NLP simple mais efficace)
# ------------------------------------------------------------

def estimate_quantity_for_ingredient(raw_text: str) -> str:
    """
    Détecte dans un texte : "200g", "300 g", "2 œufs", "3 tomates"... 
    """
    patterns = [
        r"\b\d+\s*g\b",
        r"\b\d+\s*kg\b",
        r"\b\d+\s*ml\b",
        r"\b\d+\s*l\b",
        r"\b\d+\s*(oeuf|œuf|oeufs|œufs)\b",
        r"\b\d+\s*(tomates?|oignons?|carottes?)\b",
        r"\b\d+\s*(pomme[s]? de terre)\b",
    ]

    for pat in patterns:
        m = re.search(pat, raw_text.lower())
        if m:
            return m.group(0)

    return ""


# ------------------------------------------------------------
# 5) Moteur complet — ingrédients manquants PRO
# ------------------------------------------------------------

def compute_missing_ingredients_pro(menu_text: str, inventory_df) -> List[Dict]:
    """
    Retourne une liste structurée :
    [
        {
          "nom": "...",
          "categorie": "...",
          "priorite": 1/2/3,
          "jour": "...",
          "repas": "...",
          "quantite_estimee": "200 g"
        }
    ]
    """

    if inventory_df is None or inventory_df.empty:
        return []

    # Inventaire (noms en minuscules)
    stock_names = [str(x).lower().strip() for x in inventory_df["Nom"].tolist()]

    blocks = parse_menu_structure(menu_text)
    results = []

    for blk in blocks:
        day = blk["day"]
        meal = blk["meal"]
        txt = blk["text"]

        # Détecter numéro du jour pour la priorité
        m = re.search(r"jour\s+(\d+)", day.lower())
        if m:
            d = int(m.group(1))
            if d == 1:
                priority = 1
            elif d == 2:
                priority = 2
            else:
                priority = 3
        else:
            priority = 3

        # Extraction des ingrédients probables
        candidates = extract_ingredients_from_text(txt)

        for ing in candidates:
            name = ing.strip()
            if not name:
                continue

            # Déjà en stock ?
            if any(name in s for s in stock_names):
                continue

            # Catégorie
            cat = categorize_ingredient(name)

            # Quantité estimée
            qty_est = estimate_quantity_for_ingredient(txt)

            # Éviter doublons exacts
            exists = any(r["nom"] == name and r["jour"] == day and r["repas"] == meal for r in results)
            if exists:
                continue

            results.append({
                "nom": name,
                "categorie": cat,
                "priorite": priority,
                "jour": day,
                "repas": meal,
                "quantite_estimee": qty_est
            })

    # Trier par priorité (1 = urgent)
    results.sort(key=lambda x: x["priorite"])
    return results


# ------------------------------------------------------------
# 6) Génération IA du menu (Gemini / Claude / GPT)
# ------------------------------------------------------------

from ia_utils import analyze_with_gemini, analyze_with_claude, analyze_with_openai


def generate_menu_ai(inventory_df, nb_days=5, nb_people=2, style="Équilibré", restrictions=""):
    """
    Génère un texte brut de menu via l'IA Gemini (plus stable pour ce format).
    """

    available = ", ".join(inventory_df["Nom"].tolist())

    prompt = f"""
Génère un menu anti-gaspi de {nb_days} jours pour {nb_people} personne(s).

Style : {style}
Restrictions : {restrictions}

Tiens compte des aliments en stock :
{available}

Format attendu STRICT :
Jour 1
  Petit-déjeuner : ...
  Déjeuner : ...
  Dîner : ...

Jour 2
  ...
"""

    # On utilise Gemini car il est le plus stable pour générer du texte structuré
    try:
        response = analyze_with_gemini(
            image_file=None  # Le wrapper Gemini accepte un contenu sans image
        )
    except:
        # fallback si la fonction image-only ne passe pas
        response = None

    # On doit appeler Gemini en mode texte (sans image)
    client = analyze_with_gemini.__self__ if hasattr(analyze_with_gemini, "__self__") else None
    if client:
        try:
            out = client.models.generate_content(
                model="gemini-2.0-flash-exp",
                contents=prompt
            )
            return out.text
        except:
            return "Erreur : génération menu impossible."

    return "Erreur : Gemini non disponible."
