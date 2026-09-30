import streamlit as st
from google import genai
from PIL import Image
import pypdf
from fpdf import FPDF

# Page Configuration
st.set_page_config(
    page_title="CVSpin España 🇪🇸",
    page_icon="💼",
    layout="centered"
)

# Custom Styling
st.markdown("""
    
""", unsafe_allow_html=True)

st.title("CVSpin España 🇪🇸")
st.subheader("Generador Profesional de CV para el Mercado Español")

api_key = st.secrets.get("GEMINI_API_KEY")

def clean_text_for_pdf(text):
    text = text.replace('**', '').replace('##', '').replace('#', '')
    text = text.replace('?', '-').replace('"', '').replace('•', '-')
    return text.strip()

def _render_cv_pdf(text_content, scale=1.0):
    """
    Renders the CV at a given spacing scale. scale=1.0 uses the original
    compact spacing (used to measure how tall the content naturally is).
    A scale > 1.0 stretches line heights and section gaps proportionally
    so the same content fills more vertical space, without touching any
    of the text itself.
    """
    pdf = FPDF()
    pdf.add_page()

    # Perfect margins to guarantee 1 full A4 page without crashing
    pdf.set_margins(12, 10, 12)
    pdf.set_auto_page_break(auto=False)

    # Base spacing values (same as the original design), scaled uniformly.
    line_h_header = 4.5 * scale
    line_h_bullet = 4.0 * scale
    line_h_normal = 4.2 * scale

    gap_section_before = 2.2 * scale
    gap_section_after = 0.5 * scale
    gap_bullet_after = 0.3 * scale
    gap_normal_after = 0.4 * scale
    gap_blank_line = 1.5 * scale

    lines = text_content.split('\n')
    for line in lines:
        clean_line = clean_text_for_pdf(line)
        if not clean_line:
            pdf.ln(gap_blank_line)
            continue

        try:
            safe_text = clean_line.encode('latin-1', 'replace').decode('latin-1')
        except Exception:
            safe_text = clean_line

        # Section Titles / Headers
        if line.strip().startswith('#') or (clean_line.isupper() and len(clean_line) < 40):
            pdf.ln(gap_section_before)
            pdf.set_font("Arial", 'B', size=10)
            pdf.multi_cell(0, line_h_header, safe_text)
            pdf.ln(gap_section_after)
        # Bullet points
        elif clean_line.startswith('*') or clean_line.startswith('-'):
            pdf.set_font("Arial", size=8.5)
            pdf.multi_cell(0, line_h_bullet, "  " + safe_text)
            pdf.ln(gap_bullet_after)
        # Main text / Subheaders
        else:
            pdf.set_font("Arial", size=9)
            pdf.multi_cell(0, line_h_normal, safe_text)
            pdf.ln(gap_normal_after)

    return pdf

def generate_pdf_one_page(text_content):
    """
    Two-pass render: first measure how tall the content is at the original
    compact spacing, then compute a scale factor that stretches spacing
    (line height + section/paragraph gaps) so the content naturally fills
    the whole A4 page instead of leaving blank space at the bottom.
    The text content itself is never modified.
    """
    # Pass 1: measure natural height at base (compact) spacing.
    measurement_pdf = _render_cv_pdf(text_content, scale=1.0)
    content_height = measurement_pdf.get_y() - measurement_pdf.t_margin
    usable_page_height = measurement_pdf.h - measurement_pdf.t_margin - measurement_pdf.b_margin

    if content_height > 0:
        scale = usable_page_height / content_height
    else:
        scale = 1.0

    # Never shrink below the original design, and cap how much we stretch
    # so very short CVs don't end up with absurdly wide line spacing.
    scale = max(1.0, min(scale, 1.8))

    # Pass 2: render for real using the computed scale.
    final_pdf = _render_cv_pdf(text_content, scale=scale)
    return bytes(final_pdf.output())

def call_gemini_auto(client, contents):
    available_models = []
    try:
        for m in client.models.list():
            if hasattr(m, 'supported_generation_methods') and 'generateContent' in m.supported_generation_methods:
                available_models.append(m.name)
            elif not hasattr(m, 'supported_generation_methods'):
                available_models.append(m.name)
    except Exception:
        pass
            
    if not available_models:
        available_models = ['gemini-2.5-flash', 'gemini-2.0-flash']

    last_err = None
    for model_name in available_models:
        try:
            return client.models.generate_content(
                model=model_name,
                contents=contents
            )
        except Exception as e:
            last_err = e
            continue
    raise last_err

STRICT_SPANISH_ATS_PROMPT = """
YOU ARE AN EXPERT SPANISH RECRUITER AND ATS SPECIALIST.
YOUR GOAL IS TO PRODUCE A PERFECT 100% ATS-COMPLIANT CV FOR THE SPANISH JOB MARKET (MODELO ESPAÑOL).

CRITICAL FORMATTING RULES:
- START DIRECTLY WITH THE CV CONTENT. NO INTRODUCTORY TEXT, NO GREETINGS, NO EXPLANATIONS.
- THE CONTENT MUST FIT ABSOLUTELY ON ONE SINGLE A4 PAGE.
- Keep descriptions and bullet points concise so the page is fully utilized without overflowing.

SPANISH CV STRUCTURE (Modelo Español):
1. ENCABEZADO: Full Name, Target Role, City/Country, Phone, LinkedIn.
2. PERFIL PROFESIONAL: Ultra-concise high-impact summary.
3. EXPERIENCIA PROFESIONAL: Position | Company | Dates | City.
4. EDUCACIÓN: Degree | Institution.
5. COMPETENCIAS E IDIOMAS: Hard/Soft Skills, Languages (Nativo, C1, B2).
"""

option = st.radio(
    "Seleccione la opción de entrada / اختار طريقة إدخال البيانات:",
    ("1. Ingresar datos manualmente (إدخال يدوياً)", "2. Subir documento / foto del CV (PDF, PNG, JPG)")
)

if "1. Ingresar datos" in option:
    with st.form("cv_form_manual"):
        full_name = st.text_input("Nombre Completo")
        job_title = st.text_input("Puesto de Trabajo Objetivo en España")
        experience = st.text_area("Experiencia Laboral (Empresas, Fechas, Funciones)")
        education = st.text_area("Formación Académica y Certificaciones")
        skills = st.text_input("Habilidades, Idiomas y Carné de Conducir")
        
        submitted = st.form_submit_button("Generar CV Profesional ✨")

    if submitted:
        if not api_key:
            st.error("Error de configuración en el servidor. Falta la API Key en Secrets.")
        elif not full_name or not job_title:
            st.warning("Por favor, complete los campos obligatorios.")
        else:
            with st.spinner("Procesando y optimizando el CV según las normas de España..."):
                try:
                    client = genai.Client(api_key=api_key)
                    prompt_input = f"""
{STRICT_SPANISH_ATS_PROMPT}

USER INPUT DATA:
- Nombre: {full_name}
- Puesto Objetivo: {job_title}
- Experiencia: {experience}
- Educación: {education}
- Habilidades e Idiomas: {skills}
"""
                    response = call_gemini_auto(client, prompt_input)
                    pdf_bytes = generate_pdf_one_page(response.text)
                    
                    st.success("¡CV 100% Optimizado para España generado con éxito!")
                    st.markdown("---")
                    st.markdown(response.text)
                    
                    st.download_button(
                        label="📥 Descargar CV en PDF (Normas España - 1 Página)",
                        data=pdf_bytes,
                        file_name=f"CV_{full_name.replace(' ', '_')}_Espana.pdf",
                        mime="application/pdf"
                    )
                except Exception as e:
                    st.error(f"Ocurrió un error: {e}")

else:
    uploaded_file = st.file_uploader(
        "Suba un archivo PDF o una imagen del CV (PDF, PNG, JPG, JPEG)", 
        type=["pdf", "png", "jpg", "jpeg"]
    )
    job_target_file = st.text_input("Puesto de Trabajo Objetivo en España (Opcional)")
    
    if uploaded_file is not None:
        if st.button("Extraer datos y Generar CV Optimizado ✨"):
            if not api_key:
                st.error("Error de configuración en el servidor. Falta la API Key en Secrets.")
            else:
                with st.spinner("Analizando el archivo y aplicando el estándar de España..."):
                    try:
                        client = genai.Client(api_key=api_key)
                        
                        prompt_base = f"""
{STRICT_SPANISH_ATS_PROMPT}

Target Job Title in Spain: {job_target_file if job_target_file else 'Mismo puesto detectado o perfil profesional óptimo'}
"""

                        if uploaded_file.type == "application/pdf":
                            pdf_reader = pypdf.PdfReader(uploaded_file)
                            pdf_text = ""
                            for page in pdf_reader.pages:
                                text = page.extract_text()
                                if text:
                                    pdf_text += text + "\n"
                            
                            full_prompt = f"{prompt_base}\n\nDocument Content:\n{pdf_text}"
                            response = call_gemini_auto(client, full_prompt)
                        else:
                            image = Image.open(uploaded_file)
                            response = call_gemini_auto(client, [image, prompt_base])
                        
                        pdf_bytes = generate_pdf_one_page(response.text)
                        
                        st.success("¡CV 100% Optimizado para España generado con éxito!")
                        st.markdown("---")
                        st.markdown(response.text)
                        
                        st.download_button(
                            label="📥 Descargar CV en PDF (Normas España - 1 Página)",
                            data=pdf_bytes,
                            file_name="CV_Optimizado_Espana.pdf",
                            mime="application/pdf"
                        )
                    except Exception as e:
                        st.error(f"Ocurrió un error al procesar el archivo: {e}")
