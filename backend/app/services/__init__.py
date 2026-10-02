"""Business services.

Kept as a plain package (no eager re-exports) because the services import each
other via ``from app.services import x_service``; importing them all here would
create a cycle at package initialisation time.
"""
