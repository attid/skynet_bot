from PIL import Image, ImageDraw, ImageFont

from other import img_tools


def test_create_image_with_text_uses_auto_height_when_height_is_none(tmp_path, monkeypatch):
    monkeypatch.setattr(img_tools, "start_path", str(tmp_path) + "/")

    text = "Header\nLine 1\nLine 2"
    padding_y = 24

    img_tools.create_image_with_text(text, image_size=(550, None), padding_y=padding_y)

    output_path = tmp_path / "data" / "output_image.png"
    image = Image.open(output_path)

    font = ImageFont.truetype("DejaVuSansMono.ttf", 30)
    draw = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    expected_text_height = -4
    for line in text.splitlines():
        _, top, _, bottom = draw.textbbox((0, 0), line, font=font)
        expected_text_height += bottom - top + 4

    assert image.size == (550, expected_text_height + padding_y * 2)
