import io
import json
import re

import pypdf
import streamlit as st
from docx import Document as DocxReader
from google import genai
from google.genai import types
from PIL import Image

from cv_render import build_docx, build_pdf_one_page, normalize, contact_items, \
    job_heading, job_meta, edu_heading

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
    pdf_bytes = build_pdf_one_page(cv)

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
