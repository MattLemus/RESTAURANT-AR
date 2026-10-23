# python make_card.py foto.png qr.png  ->  tarjeta.pdf (A6 para imprimir) + tarjeta.png (para compilar el .mind)
# La tarjeta completa es el marcador de fritada-mesa.html: su ancho real (10.5 cm) fija la escala del plato.
import sys
from PIL import Image, ImageDraw, ImageFont

DPI = 300
W, H = 1240, 1748  # A6 vertical (105 x 148 mm) a 300 dpi
photo, qr = Image.open(sys.argv[1]).convert('RGB'), Image.open(sys.argv[2]).convert('RGB')

card = Image.new('RGB', (W, H), 'white')
ph = round(W * photo.height / photo.width)
card.paste(photo.resize((W, ph), Image.LANCZOS), (0, 0))

q = 560
card.paste(qr.resize((q, q), Image.NEAREST), (50, ph + (H - ph - q) // 2))

d = ImageDraw.Draw(card)
bold = ImageFont.truetype('C:/Windows/Fonts/segoeuib.ttf', 74)
reg = ImageFont.truetype('C:/Windows/Fonts/segoeui.ttf', 46)
x, y = 50 + q + 30, ph + 150
for text, font, gap in (('Mira este', bold, 90), ('plato en', bold, 90), ('tu mesa', bold, 130),
                        ('Escanea el QR y', reg, 60), ('apunta a esta', reg, 60), ('tarjeta', reg, 60)):
    d.text((x, y), text, font=font, fill='black')
    y += gap

card.save('tarjeta.pdf', resolution=DPI)
card.save('tarjeta.png')
print('card', card.size, 'photo h', ph)
