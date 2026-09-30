import base64

from cryptography.hazmat.primitives import serialization
from django.core.management.base import BaseCommand
from py_vapid import Vapid01


class Command(BaseCommand):
    help = 'Generate a VAPID key pair for Web Push; put both values in secrets.json.'

    def handle(self, *args, **opts):
        vapid = Vapid01()
        vapid.generate_keys()
        private = vapid.private_key.private_bytes(serialization.Encoding.DER, serialization.PrivateFormat.PKCS8,
                                                  serialization.NoEncryption())
        public = vapid.public_key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
        b64 = lambda raw: base64.urlsafe_b64encode(raw).rstrip(b'=').decode()  # noqa: E731
        self.stdout.write(f'"VAPID_PUBLIC_KEY": "{b64(public)}",\n"VAPID_PRIVATE_KEY": "{b64(private)}"')
