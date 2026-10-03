import pyotp

from growwapi import GrowwAPI
from app.core.config import get_settings


class GrowwService:
    def __init__(self, publisher):
        self.settings = get_settings()
        self.publisher = publisher
        self.groww = None
        self.access_token = None

    def authenticate(self):
        if not self.settings.groww_totp_token:
            raise RuntimeError("GROWW_TOTP_TOKEN is not configured")

        if not self.settings.groww_totp_secret:
            raise RuntimeError("GROWW_TOTP_SECRET is not configured")

        totp = pyotp.TOTP(
            self.settings.groww_totp_secret
        ).now()

        self.access_token = GrowwAPI.get_access_token(
            api_key=self.settings.groww_totp_token,
            totp=totp,
        )

        self.groww = GrowwAPI(self.access_token)

        return {
            "status": "connected"
        }

    def get_profile(self):
        if not self.groww:
            raise RuntimeError("Groww is not authenticated")

        return self.groww.get_user_profile()