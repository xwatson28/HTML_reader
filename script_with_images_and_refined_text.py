import os
import pickle
import streamlit as st
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from google.auth.transport.requests import Request
from bs4 import BeautifulSoup, Comment
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.utils import simpleSplit, ImageReader
import requests
import io
import re
from PIL import Image
import base64
import datetime

def get_gmail_service():
    SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']
    creds = None
    if os.path.exists('token.pickle'):
        with open('token.pickle', 'rb') as token:
            creds = pickle.load(token)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        with open('token.pickle', 'wb') as token:
            pickle.dump(creds, token)

    service = build('gmail', 'v1', credentials=creds)
    return service

def base64url_decode(base64url_str):
    missing_padding = len(base64url_str) % 4
    if missing_padding:
        base64url_str += '=' * (4 - missing_padding)
    return base64.urlsafe_b64decode(base64url_str).decode('utf-8')

def list_emails(service, sender_email):
    query = f'from:{sender_email}'
    results = service.users().messages().list(userId='me', q=query, maxResults=100).execute()
    messages = results.get('messages', [])
    email_list = []
    for message in messages:
        msg = service.users().messages().get(userId='me', id=message['id']).execute()
        snippet = msg['snippet']
        headers = msg['payload']['headers']
        date_sent = None
        subject = None
        for header in headers:
            if header['name'] == 'Date':
                date_sent = header['value']
            if header['name'] == 'Subject':
                subject = header['value']
        email_list.append({
            'id': message['id'],
            'snippet': snippet,
            'date_sent': date_sent,
            'subject': subject
        })
    return email_list

def get_email_content(service, msg_id):
    msg = service.users().messages().get(userId='me', id=msg_id, format='full').execute()
    headers = msg['payload']['headers']
    date_sent = None
    for header in headers:
        if header['name'] == 'Date':
            date_sent = header['value']
            break

    for part in msg['payload']['parts']:
        if part['mimeType'] == 'text/html':
            return base64url_decode(part['body']['data']), date_sent
    
    return "", date_sent

def extract_elements_from_html(html):
    soup = BeautifulSoup(html, 'html.parser')
    elements = []

    body = soup.body

    if body is None:
        st.error("No body tag found in the HTML.")
        return elements

    body_text = str(body)

    us_index = body_text.find("Food for Thought")

    if us_index != -1:
        trimmed_body_text = body_text[us_index:]
        trimmed_soup = BeautifulSoup(trimmed_body_text, 'html.parser')
        body = trimmed_soup.body if trimmed_soup.body else trimmed_soup
    else:
        body = soup.body

    for idx, element in enumerate(body.descendants):
        if isinstance(element, Comment):
            continue
        if element.name == 'img':
            elements.append(('img', element['src'], idx))
        elif element.string and element.string.strip() and element.parent.name not in ['script', 'style']:
            elements.append(('text', element.string.strip(), idx))

    return elements

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

def download_image_in_memory(url):
    try:
        response = requests.get(url)
        if response.status_code == 200:
            return Image.open(io.BytesIO(response.content))
    except Exception as e:
        st.error(f"Error downloading image {url}: {e}")
    return None

def add_image_to_pdf(pdf, img_src, max_width, available_height, y_position):
    """
    Adds an image to the PDF, scaling it to fit within the available space while preserving quality.
    
    Parameters:
        pdf (canvas.Canvas): The PDF canvas to draw the image on.
        img_src (str): The source URL of the image.
        max_width (float): The maximum width allowed for the image.
        available_height (float): The height available for the image after text and notes.
        y_position (float): The y-coordinate where the top of the image should be placed.
    
    Returns:
        float: The y-coordinate after placing the image (for subsequent elements).
    """
    img = download_image_in_memory(img_src)
    if img:
        original_width, original_height = img.size
        aspect_ratio = original_width / original_height

        # Calculate the final width and height based on available space
        if aspect_ratio > 1:
            # Landscape orientation
            final_width = min(max_width, original_width)
            final_height = final_width / aspect_ratio
            if final_height > available_height:
                final_height = available_height
                final_width = available_height * aspect_ratio
        else:
            # Portrait orientation
            final_height = min(available_height, original_height)
            final_width = final_height * aspect_ratio
            if final_width > max_width:
                final_width = max_width
                final_height = max_width / aspect_ratio

        img_reader = ImageReader(img)
        x_position = (max_width - final_width) / 2 + 50  # Center the image horizontally

        # Draw the image centered horizontally
        pdf.drawImage(img_reader, x_position, y_position - final_height, width=final_width, height=final_height, preserveAspectRatio=True)
        
        # Return the new y_position after the image
        return y_position - final_height - 20  # Add some space after the image

    return y_position

import io
import datetime
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import simpleSplit
from reportlab.pdfgen import canvas


def create_pdf_with_selected_images(selected_images, file_name):
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    # Add the first page with the title and date
    pdf.setFont("Helvetica-Bold", 36)
    pdf.drawCentredString(width / 2, height / 2 + 20, "CLIFTON FIRST DATA")

    # Smaller font for the date
    pdf.setFont("Helvetica", 18)
    current_date = datetime.datetime.now().strftime("%B %d, %Y")
    pdf.drawCentredString(width / 2, height / 2 - 20, current_date)

    pdf.showPage()  # Move to the next page

    # Process each selected image and associated text
    for img_src, relevant_text, note in selected_images:
        text_lines = simpleSplit(relevant_text, 'Helvetica', 12, width - 100)
        note_lines = simpleSplit(note, 'Helvetica', 10, width - 100)

        text_height = len(text_lines) * 15
        note_height = len(note_lines) * 12

        y_position = height - 50
        
        # Draw the relevant text
        pdf.setFont("Helvetica", 12)
        for line in text_lines:
            pdf.drawString(50, y_position, line)
            y_position -= 15

        # Draw the image using the new add_image_to_pdf function
        available_height = height * 0.8 - text_height - note_height - 50
        y_position = add_image_to_pdf(pdf, img_src, width - 100, available_height, y_position)

        # Draw the note text
        pdf.setFont("Helvetica", 10)
        for line in note_lines:
            pdf.drawString(50, y_position, line)
            y_position -= 12

        pdf.showPage()

    pdf.save()
    buffer.seek(0)
    return buffer


# Streamlit app #



st.title("HTML Content Selector")

tab1, tab2 = st.tabs(["Upload HTML", "Daily Shot Repository"])

# Tab 1 - Used to read HTML documents that the user inputs and then spits out whatever parts the user selects
with tab1:
    uploaded_file = st.file_uploader("Upload an HTML file", type=["html"])

    if uploaded_file is not None:
        html_content = uploaded_file.read().decode('utf-8')
        elements = extract_elements_from_html(html_content)
        elements = remove_duplicate_text(elements)
        st.write("### Content in the HTML document:")

        selected_images = []
        text_accumulator = []

        for i, (element_type, content, idx) in enumerate(elements):
            if element_type == 'img':
                img_tag = f'<img src="{content}" />'
                st.markdown(img_tag, unsafe_allow_html=True)

                note = st.text_input(f'Notes for image {idx}', key=f'note_{idx}')

                if st.checkbox('Select Image above', key=f'img_{idx}'):
                    relevant_text = "\n\n".join(text_accumulator)
                    selected_images.append((content, relevant_text, note))
                
                text_accumulator = []  # Reset accumulator for the next image

            elif element_type == 'text':
                st.text(content)
                text_accumulator.append(content)

        if selected_images:
            current_date = datetime.datetime.now().strftime("%Y-%m-%d")
            default_file_name = f"The_Daily_Shot_refined_{current_date}.pdf"
            file_name = st.text_input("Enter the filename:", default_file_name)

            pdf_buffer = create_pdf_with_selected_images(selected_images, file_name)
            st.download_button("Download PDF", pdf_buffer, file_name, "application/pdf")
        else:
            st.write("No images selected.")

# Tab 2 - Used to display email content (Forwarded from the Daily Shot) on the website and allow user to extract relevant information
with tab2:
    st.write("### Select an email from the list:")
    
    service = get_gmail_service()
    sender_email = 'Editor@thedailyshot.com'
    emails = list_emails(service, sender_email)
    
    email_dict = {f"{subject} - {date_sent[:16]}": msg_id for email in emails for subject, date_sent, msg_id in [(email['subject'], email['date_sent'], email['id'])]}
    selected_email = st.selectbox("Choose an email", list(email_dict.keys()))

    if selected_email:
        email_content, date_sent = get_email_content(service, email_dict[selected_email])
        elements = extract_elements_from_html(email_content)
        elements = remove_duplicate_text(elements)

        st.write("### Content in the selected Daily Shot Edition:")
        selected_images = []
        text_accumulator = []

        for i, (element_type, content, idx) in enumerate(elements):
            if element_type == 'img':
                img_tag = f'<img src="{content}" />'
                st.markdown(img_tag, unsafe_allow_html=True)
                note = st.text_input(f'Notes for image {idx}', key=f'note_{idx}')
                
                if st.checkbox('Select Image above', key=f'img_{idx}'):
                    relevant_text = "\n\n".join(text_accumulator)
                    selected_images.append((content, relevant_text, note))

                text_accumulator = []  # Reset accumulator for the next image

            elif element_type == 'text':
                st.text(content)
                text_accumulator.append(content)

        if selected_images:
            if date_sent:
                date_obj = datetime.datetime.strptime(date_sent[:16], '%a, %d %b %Y')
                formatted_date = date_obj.strftime("%Y-%m-%d")
            else:
                formatted_date = datetime.datetime.now().strftime("%Y-%m-%d")

            default_file_name = f"The_Daily_Shot_{formatted_date}.pdf"
            file_name = st.text_input("Enter the filename:", default_file_name)

            pdf_buffer = create_pdf_with_selected_images(selected_images, file_name)
            st.download_button("Download PDF", pdf_buffer, file_name, "application/pdf")
        else:
            st.write("No images selected.")
