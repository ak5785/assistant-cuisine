# menu_pro.py

import re
import datetime
from typing import List, Dict

# --- Catégorisation simple par mots clés ---

CATEGORY_KEYWORDS = {
    "viande": ["boeuf", "bœuf", "poulet", "porc", "veau", "agneau", "lardons", "jambon", "saucisse"],
    "poisson": ["saumon", "thon", "cabillaud", "merlu", "colin", "truite", "crevette"],
    "féculent": ["pâtes", "pates", "riz", "semoule", "quinoa", "pommes de terre", "pomme de terre", "patate", "couscous"],
    "légume": ["carotte", "carottes", "courgette", "courgettes", "poivron", "poivrons", "oignon", "oignons",
               "tomate", "tomates", "brocoli", "brocolis", "salade", "épinards", "epinards"],
    "fruit": ["pomme", "pommes", "banane", "bananes", "poire", "poires", "kiwi", "fraises", "orange", "oranges"],
    "laitier": ["lait", "yaourt", "fromage", "crème", "creme", "beurre", "mozzarella", "gruyère", "cheddar"],
}


def categorize_ingredient(name: str) -> str:
    """Retourne une catégorie simple pour un ingrédient."""
    n = name.lower()
    for cat, keywords in CATEGORY_KEYWORDS.items():
        for kw in keywords:
            if kw in n:
                return cat
    return "autre"


# --- Parsing du menu IA ---

def parse_menu_structure(menu_text: str) -> List[Dict]:
    """
    Analyse le texte du menu IA et extrait des blocs du type :
    Jour X / repas / lignes d'ingrédients.
    On reste volontairement simple & robuste.
    """
    lines = menu_text.split("\n")
    current_day = None
    current_meal = None
    blocks = []

    for line in lines:
        l = line.strip()
        lower = l.lower()

        # Détection d'un "jour"
        if lower.startswith("jour ") or lower.startswith("jour"):
            current_day = l
            current_meal = None
            continue

        # Détection d'un repas
        if any(x in lower for x in ["petit-déj", "petit déj", "petit déjeuner", "petit dejeuner", "déjeuner", "dejeuner", "dîner", "diner", "collation", "dessert"]):
            current_meal = l
            continue

        # Lignes d'ingrédients ou de description associées
        if current_day and current_meal and l:
            blocks.append({
                "day": current_day,
                "meal": current_meal,
                "text": l
            })

    return blocks


# --- Extraction d'ingrédients + estimation quantités ---

def extract_ingredients_from_text(text: str) -> List[str]:
    """
    Extrait des candidats ingrédients à partir d'un texte.
    Approche simple : on coupe sur virgules / tirets / 'avec'.
    """
    # nettoyage des puces
    t = re.sub(r"[•\-••]", " ", text.lower())
    # on coupe sur virgules et 'avec'
    parts = re.split(r",| et | avec ", t)
    ingredients = []

    for p in parts:
        p = p.strip()
        if not p:
            continue
        # remove mots trop génériques
        if any(w in p for w in ["cuire", "servir", "ajouter", "mélanger", "mixer", "four", "poêle"]):
            continue
        # on garde la phrase telle quelle comme candidat
        ingredients.append(p)

    return ingredients


def estimate_quantity_for_ingredient(raw_text: str) -> str:
    """
    Essaie de trouver une quantité (ex: '200 g', '2 œufs') dans le texte.
    Retourne une chaîne libre pour affichage.
    """
    # exemples: 200g, 200 g, 2 œufs, 3 tomates...
    patterns = [
        r"\b\d+\s*g\b",
        r"\b\d+\s*kg\b",
        r"\b\d+\s*ml\b",
        r"\b\d+\s*l\b",
        r"\b\d+\s*(oeufs|œufs|oeuf|œuf)\b",
        r"\b\d+\s*(tomates?|carottes?|pommes de terre|pomme de terre)\b",
    ]

    for pat in patterns:
        m = re.search(pat, raw_text.lower())
        if m:
            return m.group(0)

    # fallback : rien trouvé
    return ""


# --- Fonction PRO principale : ingrédients manquants avec priorisation, catégories, quantités ---

def compute_missing_ingredients_pro(menu_text: str, inventory_df) -> List[Dict]:
    """
    Retourne une liste de dicts :
    {
      "nom": "...",
      "categorie": "...",
      "priorite": 1/2/3,
      "jour": "Jour 1 ...",
      "repas": "Déjeuner ...",
      "quantite_estimee": "200 g"
    }
    """

    if inventory_df is None or inventory_df.empty:
        return []

    # inventaire en minuscules pour comparaison
    stock_names = [str(x).lower().strip() for x in inventory_df["Nom"].tolist()]

    blocks = parse_menu_structure(menu_text)
    results = []

    # Mappage priorité par jour (Jour 1 = plus urgent)
    # On essaie de détecter “Jour 1”, “Jour 2”, etc.
    for blk in blocks:
        day_label = blk["day"]
        meal_label = blk["meal"]
        txt = blk["text"]

        # priorité par défaut
        priority = 3

        m = re.search(r"jour\s+(\d+)", day_label.lower())
        if m:
            day_num = int(m.group(1))
            if day_num == 1:
                priority = 1
            elif day_num == 2:
                priority = 2
            else:
                priority = 3

        # extraction ingrédients candidats
        candidates = extract_ingredients_from_text(txt)

        for cand in candidates:
            name = cand.strip()
            if not name:
                continue

            # s'il est déjà dans le stock, on ignore
            if any(name in s for s in stock_names):
                continue

            # tentative d'estimation quantité
            qty_est = estimate_quantity_for_ingredient(txt)

            # catégorie simple
            cat = categorize_ingredient(name)

            # on évite les doublons exacts (même nom + jour + repas)
            if any(r["nom"] == name and r["jour"] == day_label and r["repas"] == meal_label for r in results):
                continue

            results.append({
                "nom": name,
                "categorie": cat,
                "priorite": priority,
                "jour": day_label,
                "repas": meal_label,
                "quantite_estimee": qty_est
            })

    # tri final par priorité (1 = très urgent, 3 = moins)
    results.sort(key=lambda x: x["priorite"])
    return results


# --- Stubs pour exports (PDF / Notion) ---

def export_menu_to_pdf(menu_text: str, missing_items: List[Dict], output_path: str):
    """
    Stub : ici on pourrait utiliser reportlab ou fpdf pour générer un vrai PDF.
    Pour l'instant, on se contente d'écrire un .txt ou laisser vide.
    """
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("MENU ANTI-GASPI\n\n")
        f.write(menu_text)
        f.write("\n\nINGRÉDIENTS MANQUANTS (priorisés):\n")
        for it in missing_items:
            line = f"- [P{it['priorite']}] {it['nom']} ({it['categorie']})"
            if it["quantite_estimee"]:
                line += f" ~ {it['quantite_estimee']}"
            line += f" — {it['jour']} / {it['repas']}\n"
            f.write(line)


def export_menu_to_notion_placeholder():
    """
    Stub : à implémenter si tu veux pousser le menu vers une page Notion dédiée.
    """
    pass
