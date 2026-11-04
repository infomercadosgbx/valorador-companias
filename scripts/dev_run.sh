set -x
python -m pytest -q || true
python -m fetcher.main --only AMZN CVX GOOGL RDDT AVGO || true
python scripts/pdf_resultados.py --pendientes || true
pip install --quiet "playwright==1.58.0"
python -m playwright install --with-deps chromium > /dev/null
python scripts/pdf_resultados.py || true
mkdir -p captura/run
cp -r data/resultados data/estimaciones captura/run/ 2>/dev/null || true
for t in AMZN CVX GOOGL RDDT AVGO; do cp data/$t.json captura/run/; done
