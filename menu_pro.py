import re
import streamlit as st
import requests
from google import genai
from google.genai import types

# ============================================================
#  GÉNÉRATION IA (Gemini → fallback GPT)
# ============================================================

def gemini_generate_text(prompt: str) -> str:
    """Appel Gemini (texte uniquement, stable)."""
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
    """Fallback OpenAI GPT."""
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
#  PROMPT ULTRA OPTIMISÉ POUR MENUS ANTI-GASPI
# ============================================================

def build_prompt(nb_days, nb_people, style, restrictions, full_stock, expiring_soon):
    """Retourne le prompt optimisé (version courte mais très efficace)."""

    return f"""
Tu es un chef spécialisé en menus anti-gaspillage, cuisine familiale et équilibrée.

Génère un menu sur {nb_days} jours pour {nb_people} personnes.
Style demandé : {style}
Restrictions éventuelles : {restrictions if restrictions else "aucune"}

ALIMENTS EN STOCK :
{full_stock}

ALIMENTS À CONSOMMER EN URGENCE :
{expiring_soon}

CONTRAINTES IMPORTANTES :
- 3 repas par jour : Petit-déjeuner, Déjeuner, Dîner.
- Chaque repas doit être un VRAI PLAT cuisiné (pas une simple liste d’aliments).
- Utiliser EN PRIORITÉ les aliments proches d’expiration, mais sans répétitions.
- Respecter l’équilibre : une protéine + un légume + un accompagnement / féculent.
- Varier les types de plats (salades, poêlées, soupes, tartes, wraps, pâtes, riz…).
- Éviter les plats industriels et les aliments ultra-transformés.
- OK d'ajouter ingrédients de base (œufs, farine, lait, épices, condiments…).
- Maximum : un même aliment utilisé une seule fois par jour.
- Repas appétissants, réalistes, simples à préparer.

FORMAT STRICT :
Jour 1
  Petit-déjeuner : ...
  Déjeuner : ...
  Dîner : ...

Jour 2
  Petit-déjeuner : ...
  Déjeuner : ...
  Dîner : ...

(Continue jusqu'au Jour {nb_days})
"""


# ============================================================
#  GÉNÉRATION DE MENU
# ============================================================

def generate_menu_ai(inventory_df, nb_days=5, nb_people=2, style="Équilibré", restrictions=""):
    """Génère un menu IA optimisé (version PRO)."""

    # Tri pour mettre en avant ce qui expire vite
    inv = inventory_df.sort_values("Jours Restants", ascending=True)

    expiring_soon_list = inv[inv["Jours Restants"] <= 3]["Nom"].tolist()
    full_stock_list = inv["Nom"].tolist()

    expiring_soon = ", ".join(expiring_soon_list) if expiring_soon_list else "aucun"
    full_stock = ", ".join(full_stock_list) if full_stock_list else "aucun"

    # Création du prompt
    prompt = build_prompt
