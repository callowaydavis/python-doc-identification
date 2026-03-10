import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image, ImageSequence
import pytesseract
from pytesseract import Output
import config


def ocr_document(file_path: str, file_type: str) -> list[dict]:
    """
    OCR a PDF or TIFF file and return a list of page dicts.

    Each dict: {"page_number": int, "text": str, "confidence": float}
    """
    images = _load_images(file_path, file_type)
    results = []
    for i, image in enumerate(images, start=1):
        data = pytesseract.image_to_data(
            image,
            lang=config.TESSERACT_LANG,
            output_type=Output.DICT,
        )
        text = " ".join(w for w in data["text"] if w.strip())
        confidences = [c for c in data["conf"] if c != -1]
        mean_conf = sum(confidences) / len(confidences) if confidences else 0.0
        results.append(
            {
                "page_number": i,
                "text": text,
                "confidence": round(mean_conf, 2),
            }
        )
    return results


def _load_images(file_path: str, file_type: str) -> list:
    ft = file_type.lower().lstrip(".")
    if ft == "pdf":
        from pdf2image import convert_from_path
        return convert_from_path(file_path, dpi=config.OCR_DPI)
    elif ft in ("tif", "tiff"):
        img = Image.open(file_path)
        frames = []
        for frame in ImageSequence.Iterator(img):
            frames.append(frame.copy())
        return frames
    else:
        raise ValueError(f"Unsupported file type: {file_type}")
