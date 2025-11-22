from google import genai
from google.genai import types
import json
import streamlit as st
import requests
import re

# ===============================
#  IA GEMINI EN MODE TEXTE STABLE
# ===============================

def gemini_generate_text(prompt: str) -> str:
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
        return response.text
    except Exception as e:
        raise Exception(f"Erreur Gemini texte : {e}")

# ===============
#  Fallback GPT-4o
# ===============

def gpt_generate_text(prompt: str) -> str:
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
        "max_tokens": 1500,
        "temperature": 0.35
    }

    res = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers=headers,
        json=payload
    )

    if res.status_code != 200:
        raise Exception("Erreur OpenAI : " + res.text)

    return res.json()["choices"][0]["message"]["content"]


# ============================================================
#    FONCTION PRINCIPALE : GENERATION DE MENU 100% STABLE
# ============================================================

def generate_menu_ai(inventory_df, nb_days=5, nb_people=2, style="Équilibré", restrictions=""):
    """
    Nouvelle version stable utilisant Gemini uniquement en mode TEXTE.
    Fallback OpenAI si erreur.
    Format STRICT pour compatibilité parsing.
    """

    # Construire la liste des produits disponibles
    stock = inventory_df.sort_values("Jours Restants", ascending=True)

    expiring_soon = ", ".join(
        stock[stock["Jours Restants"] <= 3]["Nom"].tolist()
    ) or "aucun"

    full_stock = ", ".join(stock["Nom"].tolist()) or "aucun"

    # Prompt très strict et formaté
    prompt = f"""
Tu es un expert culinaire anti-gaspi.

Génère un menu sur {nb_days} jours, pour {nb_people} personne(s).
Style demandé : {style}
Restrictions alimentaires : {restrictions if restrictions else "aucune"}

LISTE DES ALIMENTS EN STOCK :
{full_stock}

ALIMENTS À CONSOMMER EN PRIORITÉ (moins de 3 jours) :
{expiring_soon}

⚠️ FORMAT FINAL STRICT A RESPECTER ABSOLUMENT :
Jour 1
  Petit-déjeuner : ...
  Déjeuner : ...
  Dîner : ...

Jour 2
  Petit-déjeuner : ...
  Déjeuner : ...
  Dîner : ...
(etc.)

⚠️ EXIGENCES IMPORTANTES :
- Toujours 3 repas par jour (Petit-déjeuner, Déjeuner, Dîner)
- Prioriser les aliments proches d'expiration
- Proposer des repas simples et réalistes
- Pas de contenu additionnel avant ou après
- Pas de JSON
- Pas de balises

Donne uniquement le texte du menu (pas d’explications).
"""

    # Essayer GEMINI (stable)
    try:
        out = gemini_generate_text(prompt).strip()
        if out.lower().startswith("jour"):
            return out
    except Exception as e:
        st.warning(f"Gemini a échoué : {e}. Fallback vers GPT…")

    # Fallback GPT-4o-mini
    out = gpt_generate_text(prompt).strip()
    if out.lower().startswith("jour"):
        return out

    return "Erreur : impossible de générer un menu valide."
