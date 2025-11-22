import streamlit as st
import base64
import io
from google import genai
from google.genai import types
import anthropic
import openai

# ============================================================
#  Utilitaires
# ============================================================

def file_to_base64(uploaded_file):
    """Convertit un fichier uploadé en base64 (pour Claude/GPT)."""
    return base64.b64encode(uploaded_file.read()).decode("utf-8")


# ============================================================
#  IA GOOGLE — GEMINI (ANALYSE D’IMAGE)
# ============================================================

def analyze_with_gemini(uploaded_file):
    """Analyse image avec Gemini et retourne une liste d’items."""
    api_key = st.secrets.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY manquante dans secrets.toml")

    client = genai.Client(api_key=api_key)

    mime = uploaded_file.type.replace("image/", "")

    image_data = uploaded_file.read()

    prompt = """
Tu es un expert en identification d’aliments.

Analyse l’image et renvoie une liste JSON STRICTE d’objets ayant exactement ces propriétés :

[
  {
    "nom": "...",
    "quantite": "1",
    "categorie": "Autre"
  }
]

CONTRAINTES :
- "nom" = aliment principal détecté
- "quantite" = estimation simple (ex : 1, 2, 3)
- "categorie" ∈ ["Viande", "Poisson", "Fruit", "Légume", "Féculent", "Produit laitier", "Condiment", "Autre"]

NE DONNE AUCUNE AUTRE SORTIE QUE DU JSON VALIDE.
"""

    try:
        response = client.models.generate_content(
            model="gemini-2.0-flash-exp",
            contents=[
                prompt,
                types.Part.from_bytes(data=image_data, mime_type=f"image/{mime}")
            ],
            config=types.GenerateContentConfig(
                temperature=0.2,
                response_mime_type="application/json"
            )
        )

        return response.parsed  # JSON déjà parsé 👍

    except Exception as e:
        raise Exception(f"Erreur Gemini Vision : {e}")


# ============================================================
#  IA ANTHROPIC — CLAUDE VISION
# ============================================================

def analyze_with_claude(uploaded_file):
    """Analyse image via Claude 3 Vision."""
    api_key = st.secrets.get("CLAUDE_API_KEY")
    if not api_key:
        raise ValueError("CLAUDE_API_KEY manquante dans secrets.toml")

    client = anthropic.Anthropic(api_key=api_key)

    b64 = file_to_base64(uploaded_file)

    prompt = """
Analyse l’image et renvoie uniquement du JSON suivant :

[
  {
    "nom": "...",
    "quantite": "1",
    "categorie": "Autre"
  }
]

Respecte strictement la structure JSON.
"""

    try:
        msg = client.messages.create(
            model="claude-3-5-sonnet-latest",
            max_tokens=350,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": uploaded_file.type,
                                "data": b64
                            },
                        },
                    ],
                }
            ],
        )

        text = msg.content[0].text
        import json
        return json.loads(text)

    except Exception as e:
        raise Exception(f"Erreur Claude Vision : {e}")


# ============================================================
#  IA OPENAI — GPT-4o Vision
# ============================================================

def analyze_with_gpt(uploaded_file):
    """Analyse image via GPT-4o Vision."""
    api_key = st.secrets.get("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY manquante dans secrets.toml")

    client = openai.OpenAI(api_key=api_key)

    b64 = file_to_base64(uploaded_file)

    prompt = """
Analyse l’image et renvoie uniquement ce JSON :

[
  {
    "nom": "...",
    "quantite": "1",
    "categorie": "Autre"
  }
]

Respect strictement le JSON.
"""

    try:
        res = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": prompt},
                        {
                            "type": "input_image",
                            "image_url": f"data:{uploaded_file.type};base64,{b64}"
                        }
                    ]
                }
            ],
            max_tokens=300,
        )

        import json
        return json.loads(res.choices[0].message.content)

    except Exception as e:
        raise Exception(f"Erreur GPT Vision : {e}")


# ============================================================
#  ROUTEUR PRINCIPAL — pour app.py
# ============================================================

def analyze_image(uploaded_file, ai_choice):
    """Choix de l’IA sélectionnée par l'utilisateur."""
    if ai_choice == "Gemini (Google)":
        return analyze_with_gemini(uploaded_file)

    elif ai_choice == "Claude (Anthropic)":
        return analyze_with_claude(uploaded_file)

    elif ai_choice == "GPT-4 Vision (OpenAI)":
        return analyze_with_gpt(uploaded_file)

    else:
        raise ValueError("IA inconnue.")
