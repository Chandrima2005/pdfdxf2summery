# import streamlit as st
# import fitz  # PyMuPDF
# import io
# import base64
# from dxfwrite import DXFEngine as dxf

# st.set_page_config(page_title="PDF / DXF Handler", layout="wide")
# st.title("📄 PDF / DXF File Handler")

# uploaded_file = st.file_uploader("Upload a file (.pdf or .dxf)", type=["pdf", "dxf"])

# if uploaded_file:
#     file_name = uploaded_file.name.lower()

#     # ---------------------------------------------------
#     # 🟢 If PDF uploaded
#     # ---------------------------------------------------
#     if file_name.endswith(".pdf"):
#         st.subheader("PDF File Detected")
#         pdf_data = uploaded_file.read()
#         pdf_doc = fitz.open(stream=pdf_data, filetype="pdf")
#         total_pages = pdf_doc.page_count

#         # Ask for page only if more than 1
#         if total_pages > 1:
#             page_number = st.number_input(
#                 "Select page number to process", 1, total_pages, 1
#             )
#         else:
#             page_number = 1

#         if st.button("Convert PDF to DXF"):
#             page = pdf_doc.load_page(page_number - 1)
#             text = page.get_text("text")

#             # Create DXF file
#             dxf_doc = dxf.drawing("converted.dxf")
#             dxf_doc.add(dxf.text(text, insert=(0, 0)))
#             buffer = io.BytesIO()
#             dxf_doc.save_to_file(buffer)
#             buffer.seek(0)

#             # Summary
#             st.subheader("✅ Conversion Summary")
#             st.write(f"**File Type:** PDF")
#             st.write(f"**Total Pages:** {total_pages}")
#             st.write(f"**Processed Page:** {page_number}")
#             st.write(f"**Extracted Characters:** {len(text)}")

#             # Download button
#             b64 = base64.b64encode(buffer.getvalue()).decode()
#             href = f'<a href="data:file/dxf;base64,{b64}" download="converted.dxf">⬇️ Download DXF File</a>'
#             st.markdown(href, unsafe_allow_html=True)

#     # ---------------------------------------------------
#     # 🟣 If DXF uploaded
#     # ---------------------------------------------------
#     elif file_name.endswith(".dxf"):
#         st.subheader("DXF File Detected")

#         # Just show summary (basic info)
#         dxf_data = uploaded_file.read()
#         st.write("✅ DXF file uploaded successfully.")
#         st.write(f"**File Size:** {len(dxf_data)/1024:.2f} KB")

#         # Download link (allow re-download)
#         b64 = base64.b64encode(dxf_data).decode()
#         href = f'<a href="data:file/dxf;base64,{b64}" download="{uploaded_file.name}">⬇️ Download Uploaded DXF</a>'
#         st.markdown(href, unsafe_allow_html=True)


# import streamlit as st
# import fitz  # PyMuPDF
# import io
# import base64
# import tempfile
# from dxfwrite import DXFEngine as dxf

# st.set_page_config(page_title="PDF / DXF File Handler", layout="wide")
# st.title("📄 PDF / DXF File Handler")

# uploaded_file = st.file_uploader("Upload a file (.pdf)", type=["pdf"])

# if uploaded_file:
#     file_name = uploaded_file.name.lower()

#     # ---------------------------------------------------
#     # 🟢 If PDF uploaded
#     # ---------------------------------------------------
#     if file_name.endswith(".pdf"):
#         st.subheader("PDF File Detected")
#         pdf_data = uploaded_file.read()
#         pdf_doc = fitz.open(stream=pdf_data, filetype="pdf")
#         total_pages = pdf_doc.page_count

#         # Ask for page only if more than 1
#         if total_pages > 1:
#             page_number = st.number_input(
#                 "Select page number to process", 1, total_pages, 1
#             )
#         else:
#             page_number = 1

#         if st.button("Convert PDF to DXF"):
#             page = pdf_doc.load_page(page_number - 1)
#             text = page.get_text("text")

#             # Create DXF file
#             dxf_doc = dxf.drawing("converted.dxf")
#             dxf_doc.add(dxf.text(text, insert=(0, 0)))

#             # Save temporarily to buffer
#             with tempfile.NamedTemporaryFile(suffix=".dxf", delete=False) as tmp:
#                 dxf_doc.saveas(tmp.name)
#                 tmp.seek(0)
#                 dxf_data = tmp.read()

#             # Summary
#             st.subheader("✅ Conversion Summary")
#             st.write(f"**File Type:** PDF")
#             st.write(f"**Total Pages:** {total_pages}")
#             st.write(f"**Processed Page:** {page_number}")
#             st.write(f"**Extracted Characters:** {len(text)}")

#             # Download button
#             st.download_button(
#                 label="⬇️ Download Converted DXF",
#                 data=dxf_data,
#                 file_name="converted.dxf",
#                 mime="application/dxf"
#             )

#     # ---------------------------------------------------
#     # 🟣 If DXF uploaded
#     # ---------------------------------------------------
#     elif file_name.endswith(".dxf"):
#         st.subheader("DXF File Detected")

#         dxf_data = uploaded_file.read()
#         st.write("✅ DXF file uploaded successfully.")
#         st.write(f"**File Size:** {len(dxf_data)/1024:.2f} KB")

#         # Download link (allow re-download)
#         st.download_button(
#             label="⬇️ Download Uploaded DXF",
#             data=dxf_data,
#             file_name=uploaded_file.name,
#             mime="application/dxf"
#         )


import streamlit as st
import fitz  # PyMuPDF
import tempfile
import ezdxf

st.set_page_config(page_title="PDF / DXF Summary Extractor", layout="wide")
st.title("📄 PDF / DXF Summary Extractor")

uploaded_file = st.file_uploader("Upload a file (.pdf or .dxf)", type=["pdf", "dxf"])


def summarize_pdf(pdf_path):
    """Extract text summary from first page of a PDF."""
    doc = fitz.open(pdf_path)
    page = doc.load_page(0)
    text = page.get_text("text")
    doc.close()

    if text.strip():
        summary = "Summary of Page 1 (Extracted Text):\n\n" + text
    else:
        summary = "No readable text found — this page may contain image-only design drawings."
    return summary


def summarize_dxf(dxf_path):
    """Extract metadata summary from DXF file using ezdxf."""
    try:
        doc = ezdxf.readfile(dxf_path)
        msp = doc.modelspace()
        summary = []
        summary.append(f"DXF Version: {doc.dxfversion}")
        summary.append(f"Number of Layouts: {len(doc.layouts)}")
        summary.append(f"Number of Layers: {len(doc.layers)}")
        summary.append(f"Number of Blocks: {len(doc.blocks)}")
        summary.append(f"Number of Entities in Modelspace: {len(msp)}")

        units = doc.header.get("$INSUNITS", None)
        unit_dict = {
            0: "Unitless",
            1: "Inches",
            2: "Feet",
            3: "Miles",
            4: "Millimeters",
            5: "Centimeters",
            6: "Meters",
            7: "Kilometers",
        }
        summary.append(f"Drawing Units: {unit_dict.get(units, 'Unknown')}")

        # List all layers
        summary.append("\nLayers:")
        for layer in doc.layers:
            summary.append(f"  - {layer.dxf.name}")

        return "\n".join(summary)
    except ezdxf.DXFError as e:
        return f"❌ Error reading DXF file: {e}"


if uploaded_file:
    file_name = uploaded_file.name.lower()

    with tempfile.NamedTemporaryFile(delete=False, suffix=file_name) as tmp:
        tmp.write(uploaded_file.read())
        tmp_path = tmp.name

    # ---------------------------------------------------
    # 🟢 PDF File
    # ---------------------------------------------------
    if file_name.endswith(".pdf"):
        st.subheader("📘 PDF File Summary")
        summary_text = summarize_pdf(tmp_path)

        st.text_area("Extracted Summary", summary_text, height=300)
        st.download_button(
            "⬇️ Download PDF Summary",
            summary_text,
            file_name="pdf_summary.txt",
            mime="text/plain",
        )

    # ---------------------------------------------------
    # 🟣 DXF File
    # ---------------------------------------------------
    elif file_name.endswith(".dxf"):
        st.subheader("📐 DXF File Summary")
        summary_text = summarize_dxf(tmp_path)

        st.text_area("Extracted Summary", summary_text, height=300)
        st.download_button(
            "⬇️ Download DXF Summary",
            summary_text,
            file_name="dxf_summary.txt",
            mime="text/plain",
        )
