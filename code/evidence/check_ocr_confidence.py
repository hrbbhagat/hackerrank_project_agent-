from pathlib import Path

from PIL import Image
import pytesseract
from pytesseract import Output


image_path = Path(
    "dataset/evidence/images/account_admin_console_20260926.png"
)

data = pytesseract.image_to_data(
    Image.open(image_path),
    config="--psm 6",
    output_type=Output.DICT,
)

words = []

for index, text in enumerate(data["text"]):
    text = text.strip()

    try:
        confidence = float(data["conf"][index])
    except (TypeError, ValueError):
        continue

    if text and confidence >= 0:
        words.append((text, confidence))

print("Image:", image_path)
print("Words with confidence:", len(words))

if words:
    average = sum(confidence for _, confidence in words) / len(words)
    print("Average confidence:", round(average, 2))

    print("\nLowest-confidence words:")
    for word, confidence in sorted(words, key=lambda item: item[1])[:20]:
        print(repr(word), round(confidence, 2))
else:
    print("No words with valid confidence scores were detected.")
