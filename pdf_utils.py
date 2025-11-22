import streamlit as st
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle, PageBreak
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.graphics.shapes import Drawing
from reportlab.graphics.barcode import qr


# ------------------------------------------------------------
# 1. Bandeau en haut de page avec thèmes
# ------------------------------------------------------------

def draw_header(canvas, doc, theme="light"):
    if theme == "dark":
        color_bg = colors.HexColor("#2C3E50")
        color_text = colors.white
    else:
        color_bg = colors.HexColor("#16A085")
        color_text = colors.white

    canvas.saveState()
    canvas.setFillColor(color_bg)
    canvas.rect(0, A4[1] - 60, A4[0], 60, fill=True)

    canvas.setFillColor(color_text)
    canvas.setFont("Helvetica-Bold", 18)
    canvas.drawString(30, A4[1] - 40, "Assistant Cuisine — Menu Anti-Gaspi")
    canvas.restoreState()


# ------------------------------------------------------------
# 2. Icônes par catégorie
# ------------------------------------------------------------

def category_icon(cat):
    icons = {
        "viande": "🥩",
        "poisson": "🐟",
        "féculent": "🥔",
        "légume": "🥕",
        "fruit": "🍎",
        "laitier": "🧀",
        "autre": "🍽️"
    }
    return icons.get(cat, "🍽️")


# ------------------------------------------------------------
# 3. Génération du PDF Premium++
# ------------------------------------------------------------

def export_menu_pdf(menu_text, missing_items, output_path,
                    logo_path=None, theme="light", app_url="https://assistant-cuisine.streamlit.app"):
    styles = getSampleStyleSheet()

    # Styles personnalisés
    body = ParagraphStyle(
        'Body',
        parent=styles['BodyText'],
        fontSize=11,
        leading=14,
        textColor=(colors.white if theme == 'dark' else colors.black)
    )
    section = ParagraphStyle(
        'Section',
        parent=styles['Heading2'],
        fontSize=14,
        textColor=(colors.HexColor('#1ABC9C') if theme == 'light' else colors.HexColor('#A3E4D7'))
    )
    urgent_title = ParagraphStyle(
        'Urgent',
        parent=styles['Heading2'],
        fontSize=14,
        textColor=colors.HexColor('#E74C3C')
    )

    doc = SimpleDocTemplate(output_path, pagesize=A4)
    story = []

    # Logo si disponible
    if logo_path:
        try:
            story.append(Image(logo_path, width=120, height=120))
            story.append(Spacer(1, 12))
        except:
            pass

    # Encadré PRODUITS URGENTS (priorité 1)
    urgent_items = [it for it in missing_items if it["priorite"] == 1]
    if urgent_items:
        story.append(Paragraph("🔥 Produits urgents à acheter :", urgent_title))
        for u in urgent_items:
            line = f"<b>{category_icon(u['categorie'])}</b> {u['nom']}"
            if u.get("quantite_estimee"):
                line += f" (~{u['quantite_estimee']})"
            story.append(Paragraph(line, body))
        story.append(Spacer(1, 20))

    # MENU COMPLET
    story.append(Paragraph("Menu complet :", section))
    story.append(Spacer(1, 6))
    story.append(Paragraph(menu_text.replace("\n", "<br/>"), body))
    story.append(PageBreak())

    # LISTE DE COURSES PRIORISÉE
    story.append(Paragraph("Liste de courses priorisée :", section))
    story.append(Spacer(1, 10))

    table_data = [["Priorité", "Ingrédient", "Catégorie", "Jour", "Repas", "Quantité"]]

    for it in missing_items:
        icon = category_icon(it["categorie"])
        table_data.append([
            f"P{it['priorite']}",
            f"{icon} {it['nom']}",
            it["categorie"],
            it["jour"],
            it["repas"],
            it.get("quantite_estimee", "")
        ])

    table = Table(table_data, colWidths=[55, 140, 80, 80, 80, 60])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#1ABC9C')),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('BOTTOMPADDING', (0,0), (-1,0), 8),
        ('BACKGROUND', (0,1), (-1,-1), colors.HexColor('#ECF0F1')),
        ('GRID', (0,0), (-1,-1), 0.5, colors.gray)
    ]))

    story.append(table)
    story.append(Spacer(1, 20))

    # QR CODE VERS L'APP
    qr_code = qr.QrCodeWidget(app_url)
    bounds = qr_code.getBounds()
    size = 120
    d = Drawing(size, size)
    d.add(qr_code)

    story.append(Paragraph("📱 Accédez à l'application :", section))
    story.append(d)

    # Build final avec bandeau
    doc.build(
        story,
        onFirstPage=lambda c, d: draw_header(c, d, theme),
        onLaterPages=lambda c, d: draw_header(c, d, theme)
    )


# ------------------------------------------------------------
# 4. Bouton Streamlit de téléchargement PDF
# ------------------------------------------------------------

def download_pdf_button(menu_text, missing_items, logo_path=None, theme="light"):
    output_path = "menu_anti_gaspi.pdf"
    export_menu_pdf(menu_text, missing_items, output_path, logo_path, theme)

    with open(output_path, "rb") as f:
        st.download_button(
            label="📄 Télécharger le PDF premium",
            data=f,
            file_name=output_path,
            mime="application/pdf"
        )
