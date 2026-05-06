import os

from PIL import Image, ImageDraw, ImageFont

from other.config_reader import start_path


def create_image_with_text(
    text,
    font_path="DejaVuSansMono.ttf",
    font_size=30,
    image_size: tuple[int, int | None] = (550, 400),
    padding_y: int = 24,
):
    """
    Create an image with the provided text centred on the canvas.
    Intermediate subtotal rows (lines with digits that start with '=') are rendered in grey.
    """
    canvas_width, canvas_height = image_size
    measure_height = canvas_height or 1
    image = Image.new("RGB", (canvas_width, measure_height), color="white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(font_path, font_size)

    lines = text.splitlines()
    if not lines:
        lines = [""]

    line_spacing = 4

    line_metrics = []
    max_line_width = 0
    total_text_height = -line_spacing

    for line in lines:
        display_line = line or " "
        left, top, right, bottom = draw.textbbox((0, 0), display_line, font=font)
        line_width = right - left
        line_height = bottom - top
        line_metrics.append((line, line_width, line_height))
        max_line_width = max(max_line_width, line_width)
        total_text_height += line_height + line_spacing

    if canvas_height is None:
        canvas_height = total_text_height + padding_y * 2
        image = Image.new("RGB", (canvas_width, canvas_height), color="white")
        draw = ImageDraw.Draw(image)

    x_base = (canvas_width - max_line_width) / 2
    y = (canvas_height - total_text_height) / 2

    for line, line_width, line_height in line_metrics:
        display_line = line or " "
        fill = "gray" if line.startswith("=") and any(char.isdigit() for char in line) else "black"
        x = (canvas_width - line_width) / 2 if line_width < canvas_width else x_base
        draw.text((x, y), display_line, font=font, fill=fill)
        y += line_height + line_spacing

    output_path = os.path.join(start_path, "data", "output_image.png")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    image.save(output_path)
