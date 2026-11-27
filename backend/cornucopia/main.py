"""ASGI entrypoint: uvicorn cornucopia.main:app"""

import logging

from cornucopia.api.app import create_app

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
app = create_app()
