"""Turns a clean rendered PDF into either (a) a rotated-but-still-digital
PDF (inv_15 — page metadata rotation only, text layer untouched) or (b)
an image with no text layer at all (inv_09/inv_10 — a real OCR test, not
a PDF-text-extraction test wearing an OCR costume).
"""

from __future__ import annotations

import io
import random

import pymupdf as fitz
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont
from pypdf import PdfReader, PdfWriter

_SEED = 20260224  # fixed — see spike/README.md, reproducibility


def rotate_pdf_page(pdf_bytes: bytes, degrees: int) -> bytes:
    """Sets the page's /Rotate flag — the text layer is untouched, only
    the presentation orientation changes. Simulates a real, common case:
    a phone-scanned PDF with correct OCR but wrong orientation metadata.
    """
    reader = PdfReader(io.BytesIO(pdf_bytes))
    writer = PdfWriter()
    for page in reader.pages:
        page.rotate(degrees)
        writer.add_page(page)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def _rasterize_first_page(pdf_bytes: bytes, *, zoom: float = 2.0) -> Image.Image:
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    page = doc[0]
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
    img = Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")
    doc.close()
    return img


def _stamp_font(pixel_size: int) -> ImageFont.ImageFont:
    # No dependency on a system TTF being installed (e.g. fonts-dejavu-core)
    # — PIL's own bundled default font supports a `size` argument as of
    # Pillow 10.1. Relying on an unpinned system font previously produced
    # a silent fallback to a near-invisible bitmap font — caught only by
    # actually looking at the rendered output, not by generation
    # succeeding without error.
    try:
        return ImageFont.load_default(size=pixel_size)
    except TypeError:  # Pillow < 10.1
        return ImageFont.load_default()


def _paid_stamp(size: tuple[int, int]) -> Image.Image:
    stamp = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(stamp)
    font = _stamp_font(size[1] - 20)
    draw.text((14, 12), "PAID", fill=(210, 20, 20, 220), font=font)
    draw.rectangle([4, 4, size[0] - 4, size[1] - 4], outline=(210, 20, 20, 220), width=6)
    return stamp.rotate(-18, expand=True)


def degrade_stamp_scan(pdf_bytes: bytes) -> bytes:
    """inv_09: image-only (no text layer), lightly rotated, a red 'PAID'
    stamp overlapping the totals area, mild blur — the stamp/annotation
    is the point of this case, not heavy image degradation.
    """
    rng = random.Random(_SEED)
    img = _rasterize_first_page(pdf_bytes)
    img = img.rotate(rng.uniform(-2.5, 2.5), expand=True, fillcolor="white")

    stamp = _paid_stamp((320, 130))
    # Positioned as a fraction of page size, not a fixed pixel offset —
    # this must actually land on/near the totals block (which sits in
    # the upper-middle third of the classic layout, not the page's
    # bottom-right corner) to test what it's meant to test. Confirmed
    # by rendering and looking at the actual output, not assumed.
    position = (int(img.width * 0.58), int(img.height * 0.30))
    img.paste(stamp, position, stamp)

    img = img.filter(ImageFilter.GaussianBlur(radius=0.6))

    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


def degrade_low_quality_scan(pdf_bytes: bytes) -> bytes:
    """inv_10: image-only, visibly skewed, blurred, low contrast, mild
    noise, and a JPEG recompression pass — a pure OCR-quality stress
    test with no semantic ambiguity in the underlying content.
    """
    rng = random.Random(_SEED + 1)
    img = _rasterize_first_page(pdf_bytes)
    img = img.rotate(rng.uniform(4.0, 6.0), expand=True, fillcolor="white")
    img = img.filter(ImageFilter.GaussianBlur(radius=1.3))
    img = ImageEnhance.Contrast(img).enhance(0.55)
    img = ImageEnhance.Brightness(img).enhance(1.08)

    noise = Image.effect_noise(img.size, 24).convert("RGB")
    img = Image.blend(img, noise, alpha=0.06)

    # Simulate scan/fax recompression artifacts.
    intermediate = io.BytesIO()
    img.save(intermediate, format="JPEG", quality=35)
    intermediate.seek(0)
    img = Image.open(intermediate).convert("RGB")

    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()
