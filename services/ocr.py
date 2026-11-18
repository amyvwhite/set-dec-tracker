import os
import fitz # PyMuPDF
from google import genai
from core.settings import load_settings
import PIL.Image
import io

def process_receipt_file(file_path):
    """
    Takes a file path (Image or PDF) and returns the raw extracted text using Gemini 2.0 Flash.
    """
    settings = load_settings()
    api_key = settings.get("gemini_api_key", "")
    if not api_key:
        print("DEBUG: Gemini API Key missing in services/ocr.py")
        return "ERROR: No Gemini API Key configured."

    client = genai.Client(api_key=api_key)
    
    try:
        # Load the file
        if file_path.lower().endswith('.pdf'):
            doc = fitz.open(file_path)
            page = doc.load_page(0) 
            pix = page.get_pixmap()
            img_bytes = pix.tobytes("png")
            img = PIL.Image.open(io.BytesIO(img_bytes))
        else:
            img = PIL.Image.open(file_path)

        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[
                "Extract all text from this receipt. Maintain layout if possible.",
                img
            ]
        )
        if not response or not response.text:
            return "ERROR: Gemini returned an empty response."
            
        return response.text
    except Exception as e:
        print(f"DEBUG: Gemini OCR Error in services/ocr.py: {e}")
        return f"ERROR: {e}"

