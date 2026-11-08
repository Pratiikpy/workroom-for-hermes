"""Create a small workbook + deck project in a folder: python make_fixture.py <folder>"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from workroom.tests.test_flagship_headless import make_deck, make_workbook  # noqa: E402

folder = Path(sys.argv[1])
folder.mkdir(parents=True, exist_ok=True)
(folder / "results.xlsx").write_bytes(make_workbook())
(folder / "deck.pptx").write_bytes(make_deck())
print(folder)
