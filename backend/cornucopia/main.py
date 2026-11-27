"""ASGI entrypoint: uvicorn cornucopia.main:app"""

from cornucopia.api.app import create_app
from cornucopia.logging_setup import configure

configure("cornucopia-api")
app = create_app()
