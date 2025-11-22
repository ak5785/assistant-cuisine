import base64
import json
import requests
from google import genai
from google.genai import types
import streamlit as st


# ------------------------------------------------------------
# Chargement des clés API depuis Streamlit Secrets
# ------------------------------------------------------------

GEMINI_KEY = st.secrets.get("GEMINI_API_KEY")
CLAUDE_KEY = st.secrets.get("CLAUDE_API_KEY")
OPENAI_KEY = st.secrets.get("OPENAI_API_KEY")

client_gemini = genai.Client(api_key=GEMINI_KEY) if GEMINI_KEY else None


# ------------------------------------------------------------
# Normalisation commune des résultats IA
# ------------------------------------------------------------

def normalize_result(data):
    """
    Convertit n'importe quel format IA → format unifié :
    [
      { "nom": "tomate", "quantite": "3", "categorie": "Légume" }
    ]
    """
    if isinstance(data, dict):
        # Parfois l’IA renvoie {"items":[...]}
        if "items" in data and isinstance(data["items"], list):
            return data["items"]
        return [data]

    if isinstance(data, list):
        return data

    return []


# ------------------------------------------------------------
# Gemini — Analyse d’image
# ------------------------------------------------------------

def analyze_with_gemini(image_file):
    if not client_gemini:
        raise ValueError("Clé API GEMINI_API_KEY manquante dans secrets.")

    image_bytes = image_file.getvalue()
    mime = image_file.type

    prompt = """
Analyse cette image et retourne UNIQUEMENT un JSON :
[
  {
    "nom": "...",
    "quantite": "...",
    "categorie": "..."
  }
]
"""

    img_part = types.Part.from_bytes(data=image_bytes, mime_type=mime)

    try:
        response = client_gemini.models.generate_content(
            model="gemini-2.0-flash-exp",
            contents=[prompt, img_part],
            config=types.GenerateContentConfig(response_mime_type="application/json")
        )

        data = json.loads(response.text)
        return normalize_result(data)

    except Exception as e:
        raise Exception(f"Erreur Gemini : {e}")


# ------------------------------------------------------------
# Claude — Analyse d’image
# ------------------------------------------------------------

def analyze_with_claude(image_file):
    if not CLAUDE_KEY:
        raise ValueError("Clé API CLAUDE_API_KEY manquante.")

    mime = image_file.type
    img_b64 = base64.b64encode(image_file.getvalue()).decode()

    prompt = """
Retourne UNIQUEMENT un JSON :
[
  {
    "nom": "...",
    "quantite": "...",
    "categorie": "..."
  }
]
"""

    headers = {
        "x-api-key": CLAUDE_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json"
    }

    payload = {
        "model": "claude-3-5-sonnet-20241022",
        "max_tokens": 2048,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": mime, "data": img_b64}},
                {"type": "text", "text": prompt}
            ]
        }]
    }

    res = requests.post("https://api.anthropic.com/v1/messages", headers=headers, json=payload)

    if res.status_code != 200:
        raise Exception(f"Claude API Error: {res.text}")

    txt = res.json()["content"][0]["text"]
    txt = txt.replace("```json", "").replace("```", "").strip()

    try:
        data = json.loads(txt)
        return normalize_result(data)
    except:
        raise Exception(f"Format JSON invalide reçu de Claude : {txt}")


# ------------------------------------------------------------
# OpenAI GPT-4 Vision — Analyse d’image
# ------------------------------------------------------------

def analyze_with_openai(image_file):
    if not OPENAI_KEY:
        raise ValueError("Clé API OPENAI_API_KEY manquante.")

    mime = image_file.type
    img_b64 = base64.b64encode(image_file.getvalue()).decode()

    prompt = """
Retourne UNIQUEMENT un JSON :
[
  {
    "nom": "...",
    "quantite": "...",
    "categorie": "..."
  }
]
"""

    headers = {
        "Authorization": f"Bearer {OPENAI_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": "gpt-4o-mini",
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{img_b64}"}}
                ]
            }
        ],
        "max_tokens": 1500
    }

    res = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload)

    if res.status_code != 200:
        raise Exception(f"OpenAI API Error: {res.text}")

    txt = res.json()["choices"][0]["message"]["content"]
    txt = txt.replace("```json", "").replace("```", "").strip()

    try:
        data = json.loads(txt)
        return normalize_result(data)
    except:
        raise Exception(f"Format JSON invalide reçu de GPT-4o : {txt}")


# ------------------------------------------------------------
# Fonction principale — Choix IA
# ------------------------------------------------------------

def analyze_image(image_file, ai_choice):
    if ai_choice == "Gemini (Google)":
        return analyze_with_gemini(image_file)

    if ai_choice == "Claude (Anthropic)":
        return analyze_with_claude(image_file)

    if ai_choice == "GPT-4 Vision (OpenAI)":
        return analyze_with_openai(image_file)

    raise ValueError("IA inconnue.")
