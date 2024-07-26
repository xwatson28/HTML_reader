import streamlit as st
from bs4 import BeautifulSoup, Comment
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.utils import simpleSplit
import requests
import os
import io
import re
from PIL import Image

# Function to remove specific text based on regular expression
def remove_specific_text(html, start_marker, end_marker):
    pattern = re.compile(re.escape(start_marker) + r".*?" + re.escape(end_marker), re.DOTALL)
    return pattern.sub('', html)

# Function to extract elements from HTML in order
def extract_elements_from_html(html):
    # Remove specific text
    html = remove_specific_text(html, "** DO NOT REDISTRIBUTE **", "Food for Thought")
    
    soup = BeautifulSoup(html, 'html.parser')
    elements = []

    def process_element(element, idx):
        if isinstance(element, Comment):
            return
        if element.name == 'img':
            elements.append(('img', element['src'], idx))
        elif element.string and element.string.strip() and element.parent.name not in ['script', 'style']:
            elements.append(('text', element.string.strip(), idx))

    for idx, element in enumerate(soup.body.descendants):
        process_element(element, idx)

    return elements

# Function to remove duplicate text while preserving order
def remove_duplicate_text(elements):
    seen_texts = set()
    unique_elements = []
    for element_type, content, idx in elements:
        if element_type == 'text':
            if content not in seen_texts:
                seen_texts.add(content)
                unique_elements.append((element_type, content, idx))
        else:
            unique_elements.append((element_type, content, idx))
    return unique_elements

# Function to download images and return local paths
def download_image(url):
    try:
        response = requests.get(url)
        if response.status_code == 200:
            local_path = os.path.join("images", os.path.basename(url))
            with open(local_path, 'wb') as file:
                file.write(response.content)
            return local_path
    except Exception as e:
        st.error(f"Error downloading image {url}: {e}")
    return None

# Function to resize image to fit within A4 size while maintaining aspect ratio
def resize_image_to_fit(image_path, max_width, max_height, text_height, note_height):
    try:
        image = Image.open(image_path)
        original_width, original_height = image.size
        aspect_ratio = original_width / original_height

        available_height = max_height - text_height - note_height - 50  # Adjusted for spacing

        if original_width > max_width or original_height > available_height:
            if aspect_ratio > 1:
                # Wider than tall
                new_width = max_width
                new_height = max_width / aspect_ratio
            else:
                # Taller than wide
                new_height = available_height
                new_width = available_height * aspect_ratio
        else:
            new_width = original_width
            new_height = original_height

        resized_image = image.resize((int(new_width), int(new_height)), Image.LANCZOS)
        resized_image_path = image_path.replace(".", "_resized.")
        resized_image.save(resized_image_path)
        return resized_image_path
    except Exception as e:
        st.error(f"Error resizing image {image_path}: {e}")
        return image_path

# Function to create a PDF with selected images, relevant texts, and notes
def create_pdf_with_selected_images(selected_images):
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    for img_src, relevant_text, note in selected_images:
        local_img_path = download_image(img_src)
        if local_img_path:
            text_lines = simpleSplit(relevant_text, 'Helvetica', 12, width - 100)
            note_lines = simpleSplit(note, 'Helvetica', 10, width - 100)
            
            text_height = len(text_lines) * 15
            note_height = len(note_lines) * 12

            resized_img_path = resize_image_to_fit(local_img_path, width - 100, height * 0.8, text_height, note_height)
            
            pdf.setFont("Helvetica", 12)
            text_y_position = height - 50
            for line in text_lines:
                pdf.drawString(50, text_y_position, line)
                text_y_position -= 15

            img_height = height * 0.8 - text_height - note_height - 50
            pdf.drawImage(resized_img_path, 50, text_y_position - img_height, width=width - 100, height=img_height, preserveAspectRatio=True, mask='auto')

            pdf.setFont("Helvetica", 10)
            note_y_position = text_y_position - img_height - 12
            for line in note_lines:
                pdf.drawString(50, note_y_position, line)
                note_y_position -= 12

            pdf.showPage()

    pdf.save()
    buffer.seek(0)
    return buffer

# Streamlit app
st.title("HTML Content Selector")

uploaded_file = st.file_uploader("Upload an HTML file", type=["html"])

if uploaded_file is not None:
    html_content = uploaded_file.read().decode('utf-8')
    elements = extract_elements_from_html(html_content)
    elements = remove_duplicate_text(elements)

    st.write("### Content in the HTML document:")
    selected_images = []
    image_notes = {}
    if not os.path.exists("images"):
        os.makedirs("images")

    for i, (element_type, content, idx) in enumerate(elements):
        if element_type == 'img':
            img_tag = f'<img src="{content}" />'
            st.markdown(img_tag, unsafe_allow_html=True)
            note = st.text_input(f'Notes for image {idx}', key=f'note_{idx}')
            if st.checkbox('Select Image above', key=f'img_{idx}'):
                relevant_text = ""
                if i > 0 and elements[i-1][0] == 'text':
                    relevant_text = elements[i-1][1]
                selected_images.append((content, relevant_text, note))
            image_notes[content] = note
        elif element_type == 'text':
            st.text(content)

    if selected_images:
        pdf_buffer = create_pdf_with_selected_images(selected_images)
        st.download_button("Download PDF", pdf_buffer, "selected_images.pdf", "application/pdf")

    else:
        st.write("No images selected.")

