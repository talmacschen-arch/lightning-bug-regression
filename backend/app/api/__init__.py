"""HTTP API subpackage (M1-10).

Each module owns one APIRouter. `app.main` mounts them under the FastAPI
app instance. Routers are kept thin — business logic lives in
`app.storage` (DB) / `app.runner` (orchestration) / `app.storage.yaml_loader`.
"""
