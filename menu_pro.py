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

def from google import genai
from google.genai import types
import streamlit as st
import requests

# ---------- IA TEXTE STABLE (Gemini + fallback GPT) ----------

def gemini_generate_text(prompt: str) -> str:
    gemini_key = st.secrets.get("GEMINI_API_KEY")
    if not gemini_key:
        raise ValueError("GEMINI_API_KEY manquante dans secrets.toml")

    client = genai.Client(api_key=gemini_key)

    res = client.models.generate_content(
        model="gemini-2.0-flash-exp",
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.35,
        )
    )
    return res.text.strip()


def gpt_generate_text(prompt: str) -> str:
    openai_key = st.secrets.get("OPENAI_API_KEY")
    if not openai_key:
        raise ValueError("OPENAI_API_KEY manquante dans secrets.toml")

    headers = {
        "Authorization": f"Bearer {openai_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "gpt-4o-mini",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 1500,
        "temperature": 0.35
    }
    res = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload)
    if res.status_code != 200:
        raise Exception(f"Erreur OpenAI : {res.text}")
    return res.json()["choices"][0]["message"]["content"].strip()


# ---------- GENERATION MENU IA STABLE ----------

def generate_menu_ai(inventory_df, nb_days=5, nb_people=2, style="Équilibré", restrictions=""):
    """
    Génère un menu texte stable, formaté, compatible avec parse_menu_structure.
    Utilise Gemini en mode texte, avec fallback GPT-4o-mini.
    """

    # Tri par urgence (jours restants)
    stock_sorted = inventory_df.sort_values("Jours Restants", ascending=True)

    expiring_soon_list = stock_sorted[stock_sorted["Jours Restants"] <= 3]["Nom"].tolist()
    full_stock_list = stock_sorted["Nom"].tolist()

    expiring_soon = ", ".join(expiring_soon_list) if expiring_soon_list else "aucun"
    full_stock = ", ".join(full_stock_list) if full_stock_list else "aucun"

    prompt = f"""
Tu es un chef spécialisé en cuisine anti-gaspi.

Génère un menu sur {nb_days} jours pour {nb_people} personne(s).
Style souhaité : {style}
Restrictions alimentaires : {restrictions if restrictions else "aucune"}.

Aliments actuellement en stock :
{full_stock}

Aliments à consommer en priorité (moins de 3 jours restants) :
{expiring_soon}

CONTRAINTES IMPORTANTES :
- Tu dois proposer 3 repas par jour : Petit-déjeuner, Déjeuner, Dîner.
- Tu dois PRIORISER l'utilisation des aliments proches de la date.
- Utilise autant que possible les aliments en stock avant d'en ajouter d'autres.
- Si un ingrédient manque vraiment et est ESSENTIEL, il pourra apparaître dans une liste de courses (mais ne t'en occupe pas ici).

FORMAT FINAL STRICT (PAS D'AUTRE TEXTE AVANT/APRÈS) :

Jour 1
  Petit-déjeuner : ...
  Déjeuner : ...
  Dîner : ...

Jour 2
  Petit-déjeuner : ...
  Déjeuner : ...
  Dîner : ...

(etc. jusqu'à Jour {nb_days})

Ne rajoute AUCUNE explication en dehors de cette structure.
Ne mets pas de balises, pas de markdown, pas de JSON.
    """.strip()

    # 1) Tentative avec Gemini
    try:
        out = gemini_generate_text(prompt)
        if out.lower().startswith("jour"):
            return out
        # si la sortie ne commence pas par "jour", on tente GPT
        st.warning("Format Gemini inattendu, tentative avec GPT-4o-mini…")
    except Exception as e:
        st.warning(f"Gemini a échoué : {e}. Tentative avec GPT-4o-mini…")

    # 2) Fallback avec GPT-4o-mini
    try:
        out = gpt_generate_text(prompt)
        if out.lower().startswith("jour"):
            return out
        else:
            return "Erreur : le modèle n'a pas respecté le format demandé."
    except Exception as e:
        return f"Erreur : impossible de générer un menu valide. Détail : {e}"

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
