"""Export the generated FileFastFlow monitor to PNG and Windows ICO."""
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parent
SIZES = [16, 24, 32, 48, 64, 128, 256]

with Image.open(ROOT / 'motion-monitor-master.png') as source:
    image = source.convert('RGBA')
    assert image.width == image.height, 'The master must be square.'
    assert image.getextrema()[3][0] == 0, 'The master must retain transparency.'
    image.resize((512, 512), Image.Resampling.LANCZOS).save(ROOT / 'logo.png')
    image.resize((256, 256), Image.Resampling.LANCZOS).save(
        ROOT / 'FileFastFlow.ico', format='ICO', sizes=[(n, n) for n in SIZES]
    )

with Image.open(ROOT / 'FileFastFlow.ico') as verified:
    assert verified.ico.sizes() == {(n, n) for n in SIZES}
print(ROOT / 'FileFastFlow.ico')
