"""QR frames for links.

The narration reads a human-friendly form of the URL (domain and path), while
the frame shows a large QR code plus the full URL as a caption.  This keeps the
audio listenable and the link usable.
"""

from __future__ import annotations

from pathlib import Path

import qrcode
from PIL import Image, ImageDraw, ImageFont

FRAME_W = 1920
FRAME_H = 1080
BACKGROUND = (255, 255, 255)
FOREGROUND = (20, 20, 20)

_FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
)


def _font(size: int) -> ImageFont.FreeTypeFont:
    for path in _FONT_CANDIDATES:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if draw.textlength(candidate, font=font) <= max_width:
            current = candidate
            continue
        if current:
            lines.append(current)
            current = ""
        # A URL has no spaces: break it by characters if needed.
        while draw.textlength(word, font=font) > max_width and len(word) > 1:
            cut = len(word)
            while cut > 1 and draw.textlength(word[:cut], font=font) > max_width:
                cut -= 1
            lines.append(word[:cut])
            word = word[cut:]
        current = word
    if current:
        lines.append(current)
    return lines or [""]


def make_qr_image(
    data: str,
    size: int,
    *,
    error_correction: int = qrcode.constants.ERROR_CORRECT_M,
    border: int = 4,
) -> Image.Image:
    """Return a square, quietly padded QR image at exactly ``size`` pixels."""
    qr = qrcode.QRCode(
        version=None,
        error_correction=error_correction,
        box_size=10,
        border=border,
    )
    qr.add_data(data)
    qr.make(fit=True)
    image = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    return image.resize((size, size), Image.Resampling.NEAREST)


def make_qr_frame(
    url: str,
    out_path: str | Path,
    *,
    width: int = FRAME_W,
    height: int = FRAME_H,
    caption: str | None = None,
) -> Path:
    """Render a 16:9 frame with a large QR code and the full URL below it."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=12,
        border=2,
    )
    qr.add_data(url)
    qr.make(fit=True)
    qr_image = qr.make_image(fill_color="black", back_color="white").convert("RGB")

    image = Image.new("RGB", (width, height), BACKGROUND)
    draw = ImageDraw.Draw(image)

    # Reserve the lower quarter for the caption.
    qr_side = int(min(width * 0.62, height * 0.68))
    qr_image = qr_image.resize((qr_side, qr_side), Image.Resampling.NEAREST)
    qr_x = (width - qr_side) // 2
    qr_y = int(height * 0.06)
    image.paste(qr_image, (qr_x, qr_y))

    text = caption or url
    max_text_width = int(width * 0.9)
    font_size = 34
    font = _font(font_size)
    lines = _wrap(draw, text, font, max_text_width)
    while len(lines) > 3 and font_size > 16:
        font_size -= 2
        font = _font(font_size)
        lines = _wrap(draw, text, font, max_text_width)

    line_height = int(font_size * 1.3)
    block_height = line_height * len(lines)
    text_y = qr_y + qr_side + int((height - (qr_y + qr_side) - block_height) / 2)
    for index, line in enumerate(lines):
        line_width = draw.textlength(line, font=font)
        draw.text(
            ((width - line_width) / 2, text_y + index * line_height),
            line,
            font=font,
            fill=FOREGROUND,
        )

    image.save(out_path, "PNG")
    return out_path
