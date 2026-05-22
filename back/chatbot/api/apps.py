import os
import threading

from django.apps import AppConfig


class ApiConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "api"

    def ready(self) -> None:
        if os.environ.get("ORDER_SPECS_SKIP_OCR_WARMUP") == "1":
            return

        def _warmup() -> None:
            from .pdf_order_analysis import warmup_easyocr_reader

            warmup_easyocr_reader()

        threading.Thread(target=_warmup, name="easyocr-warmup", daemon=True).start()
