# epub-merger

Merges two translations of the same book into one bilingual EPUB. Each sentence is followed by its translation.

## How to run

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

python3 merger.py book_fr.epub book_en.epub merged.epub --lang1 fr --lang2 en
```

`--lang1` and `--lang2` are optional and default to `fr` and `en`.
