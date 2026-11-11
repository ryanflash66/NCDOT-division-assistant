#!/usr/bin/env bash
# Vercel's Build Command (hosted/vercel.json). It lives here because vercel.json rejects a
# buildCommand longer than 256 characters, which the optional page-image step pushed past.
set -euo pipefail

(cd web && npm ci && npm run build)
python3 scripts/fetch_models.py

# Page images (DAR-654, DAR-665): only with RENDER_PAGES=1, and never allowed to fail the deploy.
# A PDF that won't download or a page that won't render only costs those images.
# They are static files under public/pages/ (the CDN serves them; vercel.json's excludeFiles keeps
# them out of the Python function), about 250 MB and, measured, 6.5 minutes of rendering plus the PDF download on top of the normal build
# (docs/redo-reports/dar-665-page-images.md).
if [ "${RENDER_PAGES:-}" = "1" ]; then
  python3 scripts/fetch_documents.py || true
  # pymupdf goes into its own folder, not the build's Python environment: the function bundle is
  # built from that environment, and a ~50 MB render-only package must not end up in it.
  render_deps="$(mktemp -d)"
  if { python3 -m pip install --target "$render_deps" pymupdf \
       || uv pip install --python python3 --target "$render_deps" pymupdf; } \
     && PYTHONPATH="$render_deps${PYTHONPATH:+:$PYTHONPATH}" python3 scripts/render_pages.py --only-indexed index/chunks.json --out public/pages; then
    :
  else
    echo "page images incomplete; deploying without the missing ones"
  fi
fi
