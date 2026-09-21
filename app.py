import streamlit as st
import pandas as pd
from google import genai
from google.genai import types
import pypdf
from PIL import Image
import io

# Page Config
st.set_page_config(
    page_title="B2B Spain Job & Lead Finder ES",
    page_icon="💼",
    layout="wide"
)

st.title("B2B Spain Job & Lead Finder ES")
st.caption("Buscador de empresas en España con ofertas activas y contactos de selección/RRHH")

# Initialize Gemini Client using Streamlit Secrets
try:
    api_key = st.secrets["GEMINI_API_KEY"]
    client = genai.Client(api_key=api_key)
except Exception as e:
    st.error("Error al cargar la clave API. Asegúrese de configurar GEMINI_API_KEY en Streamlit Secrets.")
    st.stop()

# Helper function to extract text from PDF
def extract_text_from_pdf(pdf_file):
    pdf_reader = pypdf.PdfReader(pdf_file)
    text = ""
    for page in pdf_reader.pages:
        extracted = page.extract_text()
        if extracted:
            text += extracted + "\n"
    return text

# ---------------------------------------------------------
# Model calling helper: tries a preferred model first, then
# automatically falls back through a list of alternatives if
# Google retires/renames a model (as happened with 1.5-flash
# and 2.5-flash). This avoids hardcoding a single model name
# that can 404 without warning.
# ---------------------------------------------------------
CANDIDATE_MODELS = [
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-2.5-flash",
    "gemini-2.0-flash",
]

def call_gemini_auto(client, contents):
    discovered_models = []
    try:
        for m in client.models.list():
            name = getattr(m, "name", "") or ""
            # Model names from the API may be prefixed like "models/gemini-3.6-flash"
            short_name = name.split("/")[-1] if name else ""
            if short_name:
                discovered_models.append(short_name)
    except Exception:
        pass

    # Try our known-good candidates first (in order of preference),
    # keeping only ones the API actually reports as available if we
    # managed to discover any; otherwise just try them all directly.
    if discovered_models:
        ordered_models = [m for m in CANDIDATE_MODELS if m in discovered_models]
        ordered_models += [m for m in discovered_models if m not in ordered_models]
    else:
        ordered_models = CANDIDATE_MODELS

    last_err = None
    for model_name in ordered_models:
        try:
            return client.models.generate_content(
                model=model_name,
                contents=contents
            )
        except Exception as e:
            last_err = e
            continue

    raise last_err if last_err else RuntimeError("No Gemini model available.")

# Search Mode
search_mode = st.radio(
    "Seleccione el método de búsqueda:",
    ["1. Analizar CV (PDF / Imagen)", "2. Por Sector / Domaine"]
)

cv_text = ""
image_bytes = None
sector_input = ""
uploaded_file = None

if "1. Analizar CV" in search_mode:
    uploaded_file = st.file_uploader("Suba su CV (PDF, PNG, JPG)", type=["pdf", "png", "jpg", "jpeg"])
    if uploaded_file:
        if uploaded_file.type == "application/pdf":
            cv_text = extract_text_from_pdf(uploaded_file)
        else:
            image_bytes = uploaded_file.read()
else:
    sector_input = st.text_input("Ingrese el Sector o Dominio profesional (ej. Marketing Digital, Hostelería, Software)")

city_input = st.text_input("Ciudad / Provincia en España (Opcional)", placeholder="ej. Madrid, Barcelona, Valencia")
num_companies = st.slider("Número de empresas", min_value=5, max_value=25, value=10)

if st.button("Buscar Empresas Compatibles ✨"):
    if "1. Analizar CV" in search_mode and not uploaded_file:
        st.warning("Por favor, suba un archivo de CV para continuar.")
        st.stop()
    elif "2. Por Sector" in search_mode and not sector_input:
        st.warning("Por favor, ingrese un sector o dominio profesional.")
        st.stop()

    with st.spinner("Buscando empresas y generando información de contacto..."):
        prompt = f"""
        Actúa como un experto en B2B Lead Generation y Reclutamiento en España.
        Genera una lista exacta de {num_companies} empresas reales ubicadas o activas en España {f'en la zona de {city_input}' if city_input else ''} que tengan necesidades activas de contratación o encajen perfectamente con el perfil provisto.

        Perfil / Requisitos:
        {cv_text if cv_text else sector_input}

        Para cada empresa devuelve estrictamente los siguientes campos estructurados:
        1. Nombre de la empresa
        2. Sector / Industria
        3. Ciudad / Ubicación en España
        4. Razón del encaje (Por qué necesitan este perfil)
        5. Email de contacto / Selección / RRHH (o formato estándar estimado ej. rrhh@empresa.es)
        6. Teléfono o enlace de ofertas de empleo

        Formatea la respuesta en una tabla Markdown clara y estructurada.
        """

        try:
            contents = [prompt]
            if image_bytes:
                contents.append(types.Part.from_bytes(data=image_bytes, mime_type=uploaded_file.type))

            response = call_gemini_auto(client, contents)

            st.success("¡Búsqueda completada exitosamente!")
            st.markdown(response.text)

        except Exception as e:
            st.error(f"Error: {str(e)}")
