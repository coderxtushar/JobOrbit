#!/bin/sh
# Regenerate src/types/api.d.ts from the FastAPI schema. Run from frontend/ after a backend
# change. Uses the backend's own virtualenv, so no server needs to be running.
set -e
cd "$(dirname "$0")/.."
../.venv/bin/python -c "import json, app.main as m; print(json.dumps(m.create_app().openapi()))" \
  > .openapi.json 2>/dev/null || (cd .. && .venv/bin/python -c "import json, app.main as m; print(json.dumps(m.create_app().openapi()))" > frontend/.openapi.json)
npx openapi-typescript .openapi.json -o src/types/api.d.ts
rm -f .openapi.json
