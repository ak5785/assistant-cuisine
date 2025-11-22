import io
import qrcode
import datetime
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
import streamlit as st


# ============================================================
#  Génération QR code
# ============================================================

def generate_qr_code(url="https://assistant-cuisine.streamlit.app"):
    """Crée une image QR code en mémoire (PNG)."""
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=4,
        border=2,
    )
    qr.add_data(url)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")

    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer


# ============================================================
#  Styles PDF
# ============================================================

def get_styles(theme="light"):
    styles = getSampleStyleSheet()

    if theme == "dark":
        text_color = colors.whitesmoke
        bg_color = colors.HexColor("#1E1E1E")
        accent = colors.HexColor("#27AE60")
    else:
        text_color = colors.black
        bg_color = colors.white
        accent = colors.HexColor("#2E86C1")

    title = ParagraphStyle(
        "title",
        parent=styles["Title"],
        fontSize=22,
        textColor=text_color,
        alignment=1,
        spaceAfter=12,
    )

    h2 = ParagraphStyle(
        "h2",
        parent=styles["Heading2"],
        fontSize=16,
        textColor=accent,
        spaceAfter=8,
    )

    normal = ParagraphStyle(
        "normal",
        parent=styles["BodyText"],
        fontSize=11,
        textColor=text_color,
        leading=15,
    )

    urgent = ParagraphStyle(
        "urgent",
        parent=styles["BodyText"],
        fontSize=12,
        textColor=colors.red,
        leading=16,
    )

    return {
        "title": title,
        "h2": h2,
        "normal": normal,
        "urgent": urgent,
        "bg": bg_color,
        "accent": accent,
    }


# ============================================================
#  Création du PDF premium
# ============================================================

def build_pdf(menu_text, missing_items, theme="light"):
    """
    Construit le PDF en mémoire et renvoie un buffer prêt à télécharger.
    """

    buffer = io.BytesIO()

    styles = get_styles(theme)

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
    )

    elements = []

    # ------------------------------------------------------------
    # Bandeau haut
    # ------------------------------------------------------------
    today = datetime.date.today().strftime("%d %B %Y")
    title = f"Menu Anti-Gaspi — {today}"
    elements.append(Paragraph(title, styles["title"]))
    elements.append(Spacer(1, 0.4 * cm))

    # ------------------------------------------------------------
    # Section : Menu complet
    # ------------------------------------------------------------
    elements.append(Paragraph("🍽️ Menu généré", styles["h2"]))

    for line in menu_text.split("\n"):
        elements.append(Paragraph(line, styles["normal"]))

    elements.append(Spacer(1, 0.6 * cm))

    # ------------------------------------------------------------
    # Section : Produits urgents
    # ------------------------------------------------------------
    urgents = [it for it in missing_items if it["priorite"] == 1]

    if urgents:
        elements.append(Paragraph("🔥 Produits très importants", styles["h2"]))
        for it in urgents:
            txt = f"- {it['nom']} (pour {it['jour']} — {it['repas']})"
            elements.append(Paragraph(txt, styles["urgent"]))
        elements.append(Spacer(1, 0.5 * cm))

    # ------------------------------------------------------------
    # Section : Liste de courses complète
    # ------------------------------------------------------------
    elements.append(Paragraph("🛒 Liste de courses", styles["h2"]))

    if not missing_items:
        elements.append(Paragraph("Aucun ingrédient manquant 🎉", styles["normal"]))
    else:
        data = [["Ingrédient", "Jour", "Repas", "Priorité"]]

        for it in missing_items:
            badge = (
                "🔥 P1"
                if it["priorite"] == 1
                else ("⚠️ P2" if it["priorite"] == 2 else "🟢 P3")
            )
            data.append([
                it["nom"],
                it["jour"],
                it["repas"],
                badge,
            ])

        table = Table(data, colWidths=[6 * cm, 3 * cm, 3 * cm, 3 * cm])

        table_style = TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), styles["accent"]),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 12),

            ('BACKGROUND', (0, 1), (-1, -1), colors.whitesmoke),
            ('TEXTCOLOR', (0, 1), (-1, -1), colors.black),

            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('ALIGN', (1, 1), (-1, -1), 'CENTER'),
        ])

        table.setStyle(table_style)
        elements.append(table)

    elements.append(Spacer(1, 1 * cm))

    # ------------------------------------------------------------
    # QR Code vers l’app Streamlit
    # ------------------------------------------------------------
    elements.append(Paragraph("🔗 Ouvrir l'application", styles["h2"]))

    qr_buffer = generate_qr_code()
    from reportlab.platypus import Image
    qr_img = Image(qr_buffer, width=4 * cm, height=4 * cm)

    elements.append(qr_img)

    # ------------------------------------------------------------
    # Construction du PDF
    # ------------------------------------------------------------
    doc.build(elements)

    buffer.seek(0)
    return buffer


# ============================================================
#  Bouton Streamlit pour télécharger le PDF
# ============================================================

def download_pdf_button(menu_text, missing_items, logo_path=None, theme="light"):
    """Crée le bouton Streamlit pour télécharger le PDF."""

    buffer = build_pdf(menu_text, missing_items, theme)

    st.download_button(
        label="📄 Télécharger le PDF",
        data=buffer,
        file_name="menu_anti_gaspi.pdf",
        mime="application/pdf",
        use_container_width=True,
    )
