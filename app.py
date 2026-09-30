import io
import json
import re

import pypdf
import streamlit as st
from docx import Document
from docx import Document as DocxReader
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor, Cm
from fpdf import FPDF
from google import genai
from google.genai import types
from PIL import Image

# requirements.txt: streamlit, google-genai, pypdf, pillow, fpdf2, python-docx

# =====================================================================
# CV RENDERING (Word + PDF)
# =====================================================================

# ----- Colours (hex) -----
C_DARK = "1A1A1A"
C_BLUE = "2F5496"
C_GREY = "595959"
C_TEXT = "262626"
C_LINE = "BFBFBF"

PLACEHOLDER_EDU = "[AÑADIR FORMACIÓN ACADÉMICA - no especificada en el CV original]"
PLACEHOLDER_LANG = "[NIVEL CEFR A CONFIRMAR]"


def _g(d, key, default=""):
    v = d.get(key, default)
    return v.strip() if isinstance(v, str) else (v or default)


def normalize(cv):
    """Fill gaps with visible placeholders instead of inventing data."""
    cv = dict(cv)
    if not cv.get("education"):
        cv["education"] = [{"degree": PLACEHOLDER_EDU, "institution": "", "dates": ""}]
    langs = []
    for l in cv.get("languages") or []:
        if isinstance(l, str):
            l = {"language": l, "level": ""}
        if not _g(l, "level"):
            l["level"] = PLACEHOLDER_LANG
        langs.append(l)
    cv["languages"] = langs
    return cv


def contact_items(cv):
    items = [_g(cv, "location"), _g(cv, "phone"), _g(cv, "email"), _g(cv, "linkedin")]
    items = [i for i in items if i]
    lic = _g(cv, "driving_license")
    return items, (f"Permiso de conducir: {lic}" if lic else "")


def job_heading(job):
    parts = [_g(job, "title"), _g(job, "company")]
    return " | ".join(p for p in parts if p)


def job_meta(job):
    parts = [_g(job, "dates"), _g(job, "city")]
    return " | ".join(p for p in parts if p)


def edu_heading(e):
    parts = [_g(e, "degree"), _g(e, "institution")]
    return " | ".join(p for p in parts if p)


# =====================================================================
# DOCX
# =====================================================================
def _rgb(hex_):
    return RGBColor.from_string(hex_)


def _add_run(p, text, size, color, bold=False, italic=False):
    r = p.add_run(text)
    r.font.size = Pt(size)
    r.font.color.rgb = _rgb(color)
    r.bold = bold
    r.italic = italic
    return r


def _spacing(p, before=0, after=0):
    p.paragraph_format.space_before = Pt(before)
    p.paragraph_format.space_after = Pt(after)
    p.paragraph_format.line_spacing = 1.0


def _bottom_border(p):
    pPr = p._p.get_or_add_pPr()
    pbdr = OxmlElement("w:pBdr")
    b = OxmlElement("w:bottom")
    b.set(qn("w:val"), "single")
    b.set(qn("w:sz"), "4")
    b.set(qn("w:space"), "2")
    b.set(qn("w:color"), C_LINE)
    pbdr.append(b)
    pPr.append(pbdr)


def _section(doc, title):
    p = doc.add_paragraph()
    _spacing(p, before=10, after=4)
    _add_run(p, title, 10, C_BLUE, bold=True)
    _bottom_border(p)


def _bullet(doc, text):
    p = doc.add_paragraph(style="List Bullet")
    _spacing(p, after=2)
    _add_run(p, text, 9, C_TEXT)


def build_docx(cv_data) -> bytes:
    cv = normalize(cv_data)
    doc = Document()

    sec = doc.sections[0]
    sec.page_width, sec.page_height = Cm(21.0), Cm(29.7)  # A4
    sec.left_margin = sec.right_margin = Cm(1.5)
    sec.top_margin = sec.bottom_margin = Cm(1.3)

    normal = doc.styles["Normal"]
    normal.font.name = "Calibri"
    normal.element.rPr.rFonts.set(qn("w:eastAsia"), "Calibri")
    normal.font.size = Pt(9)

    # Header
    p = doc.add_paragraph()
    _spacing(p, after=2)
    _add_run(p, _g(cv, "name").upper(), 17, C_DARK, bold=True)

    if _g(cv, "target_role"):
        p = doc.add_paragraph()
        _spacing(p, after=6)
        _add_run(p, _g(cv, "target_role"), 10, C_BLUE)

    items, lic = contact_items(cv)
    p = doc.add_paragraph()
    _spacing(p, after=8)
    for i, it in enumerate(items):
        if i:
            _add_run(p, "  |  ", 9, C_GREY)
        _add_run(p, it, 9, C_GREY)
    if lic:
        if items:
            _add_run(p, "  |  ", 9, C_GREY)
        _add_run(p, lic, 9, C_GREY, bold=True)

    # Profile
    if _g(cv, "profile"):
        _section(doc, "PERFIL PROFESIONAL")
        p = doc.add_paragraph()
        _spacing(p, after=5)
        p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        _add_run(p, _g(cv, "profile"), 9, C_TEXT)

    # Experience
    if cv.get("experience"):
        _section(doc, "EXPERIENCIA PROFESIONAL")
        for job in cv["experience"]:
            p = doc.add_paragraph()
            _spacing(p, before=5, after=1)
            _add_run(p, job_heading(job), 9.5, C_DARK, bold=True)
            if job_meta(job):
                p = doc.add_paragraph()
                _spacing(p, after=3)
                _add_run(p, job_meta(job), 8.5, C_GREY, italic=True)
            for b in job.get("bullets") or []:
                _bullet(doc, b)

    # Education
    _section(doc, "EDUCACIÓN / FORMACIÓN")
    for e in cv["education"]:
        p = doc.add_paragraph()
        _spacing(p, before=2, after=1)
        _add_run(p, edu_heading(e), 9.5, C_DARK, bold=True)
        if _g(e, "dates"):
            p = doc.add_paragraph()
            _spacing(p, after=2)
            _add_run(p, _g(e, "dates"), 8.5, C_GREY, italic=True)

    # Skills
    if cv.get("skills"):
        _section(doc, "COMPETENCIAS")
        for s in cv["skills"]:
            _bullet(doc, s)

    # Languages
    if cv.get("languages"):
        _section(doc, "IDIOMAS")
        for l in cv["languages"]:
            _bullet(doc, f"{_g(l, 'language')}: {_g(l, 'level')}")

    # Interests
    if _g(cv, "interests"):
        _section(doc, "INTERESES")
        p = doc.add_paragraph()
        _spacing(p, after=2)
        _add_run(p, _g(cv, "interests"), 9, C_TEXT)

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


# =====================================================================
# PDF (one A4 page, same look)
# =====================================================================
def _safe(t):
    t = (t or "")
    for a, b in (("–", "-"), ("—", "-"), ("•", "-"), ("“", '"'), ("”", '"'),
                 ("‘", "'"), ("’", "'"), ("…", "...")):
        t = t.replace(a, b)
    return t.encode("latin-1", "replace").decode("latin-1")


def _hex(h):
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _render_pdf(cv, sp=1.0, fs=1.0):
    """sp = spacing multiplier, fs = font-size multiplier."""
    L, R, T = 15, 15, 12
    pdf = FPDF(unit="mm", format="A4")
    pdf.set_margins(L, T, R)
    pdf.set_auto_page_break(auto=False)
    pdf.add_page()
    W = pdf.w - L - R

    def font(size, style=""):
        pdf.set_font("Helvetica", style, size * fs)

    def color(h):
        pdf.set_text_color(*_hex(h))

    def line(text, size, col, style="", h=4.4, after=0.0, before=0.0, align="L"):
        if before:
            pdf.ln(before * sp)
        font(size, style)
        color(col)
        pdf.multi_cell(0, h * sp * fs, _safe(text), align=align,
                       new_x="LMARGIN", new_y="NEXT")
        if after:
            pdf.ln(after * sp)

    def section(title):
        pdf.ln(3.2 * sp)
        font(10, "B")
        color(C_BLUE)
        pdf.cell(0, 4.6 * sp * fs, _safe(title), new_x="LMARGIN", new_y="NEXT")
        y = pdf.get_y() + 0.4
        pdf.set_draw_color(*_hex(C_LINE))
        pdf.set_line_width(0.2)
        pdf.line(L, y, L + W, y)
        pdf.ln(1.6 * sp)

    def bullet(text):
        font(9)
        color(C_TEXT)
        h = 4.1 * sp * fs
        pdf.cell(4, h, "-")
        pdf.set_left_margin(L + 4)
        pdf.set_x(L + 4)
        pdf.multi_cell(0, h, _safe(text), new_x="LMARGIN", new_y="NEXT")
        pdf.set_left_margin(L)
        pdf.set_x(L)
        pdf.ln(0.5 * sp)

    # Header
    line(_g(cv, "name").upper(), 17, C_DARK, "B", h=7.5, after=0.8)
    if _g(cv, "target_role"):
        line(_g(cv, "target_role"), 10, C_BLUE, h=4.8, after=1.2)
    items, lic = contact_items(cv)
    contact = "  |  ".join(items + ([lic] if lic else []))
    if contact:
        line(contact, 9, C_GREY, h=4.4, after=1.0)

    if _g(cv, "profile"):
        section("PERFIL PROFESIONAL")
        line(_g(cv, "profile"), 9, C_TEXT, h=4.3, align="J", after=0.8)

    if cv.get("experience"):
        section("EXPERIENCIA PROFESIONAL")
        for job in cv["experience"]:
            line(job_heading(job), 9.5, C_DARK, "B", h=4.6, before=1.6)
            if job_meta(job):
                line(job_meta(job), 8.5, C_GREY, "I", h=4.0, after=0.6)
            for b in job.get("bullets") or []:
                bullet(b)

    section("EDUCACIÓN / FORMACIÓN")
    for e in cv["education"]:
        line(edu_heading(e), 9.5, C_DARK, "B", h=4.6, before=0.6)
        if _g(e, "dates"):
            line(_g(e, "dates"), 8.5, C_GREY, "I", h=4.0)

    if cv.get("skills"):
        section("COMPETENCIAS")
        for s in cv["skills"]:
            bullet(s)

    if cv.get("languages"):
        section("IDIOMAS")
        for l in cv["languages"]:
            bullet(f"{_g(l, 'language')}: {_g(l, 'level')}")

    if _g(cv, "interests"):
        section("INTERESES")
        line(_g(cv, "interests"), 9, C_TEXT, h=4.3)

    return pdf


def build_pdf_one_page(cv_data) -> bytes:
    """
    1) If the content is too long, shrink the fonts slightly (down to 80%).
    2) If it is short, stretch spacing (up to x1.8) so the page looks filled.
    The text itself is never changed.
    """
    cv = normalize(cv_data)
    usable = None

    fs = 1.0
    while True:
        probe = _render_pdf(cv, sp=1.0, fs=fs)
        usable = probe.h - 12 - 12          # top margin 12, bottom reserve 12
        used = probe.get_y() - 12
        if used <= usable or fs <= 0.8:
            break
        fs = round(fs - 0.02, 2)

    sp = max(1.0, min(usable / used, 1.8)) if used > 0 else 1.0
    # Safety: make sure the stretched version still fits
    while sp > 1.0:
        final = _render_pdf(cv, sp=sp, fs=fs)
        if final.get_y() - 12 <= usable:
            break
        sp = round(sp - 0.02, 2)
    final = _render_pdf(cv, sp=max(sp, 1.0), fs=fs)
    return bytes(final.output())


# =====================================================================
# STREAMLIT APP
# =====================================================================
st.set_page_config(page_title="CVSpin España 🇪🇸", page_icon="💼", layout="centered")

st.title("CVSpin España 🇪🇸")
st.subheader("Generador Profesional de CV para el Mercado Español")

api_key = st.secrets.get("GEMINI_API_KEY")

# ---------------------------------------------------------------------
# Prompt: Gemini returns STRUCTURED JSON (not free text), so the layout
# is always identical: header, profile, experience, education, skills,
# languages, interests.
# ---------------------------------------------------------------------
STRICT_SPANISH_ATS_PROMPT = """
You are an expert Spanish recruiter and ATS specialist.
Convert the input into a CV for the Spanish job market (modelo español).
Write ALL text in Spanish.

Return ONLY valid JSON (no markdown, no backticks, no comments) with exactly this schema:
{
  "name": "Full name",
  "target_role": "Role 1 | Role 2 | Role 3",
  "location": "City, Country",
  "phone": "",
  "email": "",
  "linkedin": "",
  "driving_license": "B",
  "profile": "2-3 sentence professional summary, high impact, ends with the target roles in Spain",
  "experience": [
    {"title": "Position", "company": "Company", "dates": "Mes AAAA – Mes AAAA",
     "city": "City, Country", "bullets": ["3 to 4 short action-verb bullets"]}
  ],
  "education": [{"degree": "", "institution": "", "dates": ""}],
  "skills": ["6 to 8 short skills"],
  "languages": [{"language": "Francés", "level": "C1"}],
  "interests": ""
}

RULES:
- NEVER invent data (employers, dates, degrees, language levels, phone numbers).
  If something is missing use "" (for education use an empty list, for a language level use "").
- Most recent job first. Bullets start with a verb in infinitive/noun form, max ~15 words each.
- Keep it concise: the whole CV MUST fit on ONE A4 page.
"""


def call_gemini_json(client, contents):
    cfg = types.GenerateContentConfig(response_mime_type="application/json")

    models = []
    try:
        for m in client.models.list():
            name = m.name or ""
            if "gemini" in name and "flash" in name and "image" not in name:
                models.append(name)
    except Exception:
        pass
    if not models:
        models = ["gemini-2.5-flash", "gemini-2.0-flash"]

    last_err = None
    for name in models:
        try:
            return client.models.generate_content(model=name, contents=contents, config=cfg)
        except Exception as e:
            last_err = e
    raise last_err


def parse_json(text):
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, flags=re.S)
        if not m:
            raise
        return json.loads(m.group(0))


def read_docx(file):
    d = DocxReader(io.BytesIO(file.getvalue()))
    parts = [p.text for p in d.paragraphs if p.text.strip()]
    for t in d.tables:
        for row in t.rows:
            parts.append(" | ".join(c.text for c in row.cells))
    return "\n".join(parts)


def show_result(cv_data, file_stub):
    cv = normalize(cv_data)
    docx_bytes = build_docx(cv)
    try:
        pdf_bytes = build_pdf_one_page(cv)
    except Exception as e:
        pdf_bytes = None
        st.warning(f"No se pudo generar el PDF ({e}). Descargue la versión Word.")

    st.success("¡CV optimizado para España generado con éxito!")
    st.markdown("---")

    # Preview
    items, lic = contact_items(cv)
    st.markdown(f"## {cv.get('name', '').upper()}")
    if cv.get("target_role"):
        st.markdown(f"**{cv['target_role']}**")
    st.caption("  |  ".join(items + ([lic] if lic else [])))
    if cv.get("profile"):
        st.markdown("**PERFIL PROFESIONAL**")
        st.write(cv["profile"])
    if cv.get("experience"):
        st.markdown("**EXPERIENCIA PROFESIONAL**")
        for j in cv["experience"]:
            st.markdown(f"**{job_heading(j)}**  \n*{job_meta(j)}*")
            for b in j.get("bullets") or []:
                st.markdown(f"- {b}")
    st.markdown("**EDUCACIÓN / FORMACIÓN**")
    for e in cv["education"]:
        st.markdown(f"- {edu_heading(e)}")
    if cv.get("skills"):
        st.markdown("**COMPETENCIAS**")
        for s in cv["skills"]:
            st.markdown(f"- {s}")
    if cv.get("languages"):
        st.markdown("**IDIOMAS**")
        for l in cv["languages"]:
            st.markdown(f"- {l.get('language', '')}: {l.get('level', '')}")
    if cv.get("interests"):
        st.markdown("**INTERESES**")
        st.write(cv["interests"])

    if any("[" in edu_heading(e) for e in cv["education"]) or \
       any("[" in (l.get("level") or "") for l in cv["languages"]):
        st.warning("Hay campos entre [corchetes] que debe completar (formación / nivel de idiomas).")

    c1, c2 = st.columns(2)
    c1.download_button("📥 Descargar en Word (.docx)", docx_bytes,
                       file_name=f"CV_{file_stub}_Espana.docx",
                       mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    if pdf_bytes:
        c2.download_button("📥 Descargar en PDF (1 página)", pdf_bytes,
                           file_name=f"CV_{file_stub}_Espana.pdf", mime="application/pdf")


option = st.radio(
    "Seleccione la opción de entrada / اختار طريقة إدخال البيانات:",
    ("1. Ingresar datos manualmente (إدخال يدوياً)",
     "2. Subir documento / foto del CV (PDF, DOCX, PNG, JPG)"),
)

# ---------------------------------------------------------------------
# Option 1: manual form
# ---------------------------------------------------------------------
if option.startswith("1"):
    with st.form("cv_form_manual"):
        full_name = st.text_input("Nombre Completo")
        job_title = st.text_input("Puesto de Trabajo Objetivo en España")
        contact = st.text_input("Ciudad, Teléfono, Email, LinkedIn")
        experience = st.text_area("Experiencia Laboral (Empresas, Fechas, Funciones)")
        education = st.text_area("Formación Académica y Certificaciones")
        skills = st.text_input("Habilidades, Idiomas y Carné de Conducir")
        submitted = st.form_submit_button("Generar CV Profesional ✨")

    if submitted:
        if not api_key:
            st.error("Falta la API Key en Secrets.")
        elif not full_name or not job_title:
            st.warning("Por favor, complete los campos obligatorios.")
        else:
            with st.spinner("Procesando y optimizando el CV según las normas de España..."):
                try:
                    client = genai.Client(api_key=api_key)
                    prompt = f"""{STRICT_SPANISH_ATS_PROMPT}

USER INPUT DATA:
- Nombre: {full_name}
- Puesto Objetivo: {job_title}
- Contacto: {contact}
- Experiencia: {experience}
- Educación: {education}
- Habilidades e Idiomas: {skills}
"""
                    resp = call_gemini_json(client, prompt)
                    show_result(parse_json(resp.text), full_name.replace(" ", "_"))
                except Exception as e:
                    st.error(f"Ocurrió un error: {e}")

# ---------------------------------------------------------------------
# Option 2: upload PDF / DOCX / image
# ---------------------------------------------------------------------
else:
    uploaded = st.file_uploader("Suba su CV (PDF, DOCX, PNG, JPG, JPEG)",
                                type=["pdf", "docx", "png", "jpg", "jpeg"])
    target = st.text_input("Puesto de Trabajo Objetivo en España (Opcional)")

    if uploaded is not None and st.button("Extraer datos y Generar CV Optimizado ✨"):
        if not api_key:
            st.error("Falta la API Key en Secrets.")
        else:
            with st.spinner("Analizando el archivo y aplicando el estándar de España..."):
                try:
                    client = genai.Client(api_key=api_key)
                    base = f"""{STRICT_SPANISH_ATS_PROMPT}

Target job title in Spain: {target or 'same role detected in the CV, or the best-fitting profile'}
"""
                    name = uploaded.name.lower()
                    if name.endswith(".pdf"):
                        reader = pypdf.PdfReader(uploaded)
                        txt = "\n".join((p.extract_text() or "") for p in reader.pages)
                        contents = f"{base}\n\nDocument content:\n{txt}"
                    elif name.endswith(".docx"):
                        contents = f"{base}\n\nDocument content:\n{read_docx(uploaded)}"
                    else:
                        contents = [Image.open(uploaded), base]

                    resp = call_gemini_json(client, contents)
                    data = parse_json(resp.text)
                    show_result(data, (data.get("name") or "Optimizado").replace(" ", "_"))
                except Exception as e:
                    st.error(f"Ocurrió un error al procesar el archivo: {e}")
