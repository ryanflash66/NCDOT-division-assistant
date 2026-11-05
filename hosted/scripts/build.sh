#!/usr/bin/env bash
# Vercel's Build Command (hosted/vercel.json). It lives here because vercel.json rejects a
# buildCommand longer than 256 characters, which the optional page-image step pushed past.
set -euo pipefail

(cd web && npm ci && npm run build)
python3 scripts/fetch_models.py

# Page images (DAR-654): only with RENDER_PAGES=1, and never allowed to fail the deploy.
# A PDF that won't download or a page that won't render only costs those images.
if [ "${RENDER_PAGES:-}" = "1" ]; then
  python3 scripts/fetch_documents.py || true
  if python3 -m pip install --quiet pymupdf \
     && python3 scripts/render_pages.py --only-indexed index/chunks.json --out public/pages; then
    :
  else
    echo "page images incomplete; deploying without the missing ones"
  fi
fi
