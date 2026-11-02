import socket
import struct
from collections.abc import Iterable
from dataclasses import dataclass

from django.conf import settings


class AntivirusUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class AntivirusResult:
    clean: bool
    signature: str = ""


class ClamAVScanner:
    def scan(self, chunks: Iterable[bytes]) -> AntivirusResult:
        try:
            with socket.create_connection(
                (settings.CLAMAV_HOST, settings.CLAMAV_PORT),
                timeout=settings.CLAMAV_TIMEOUT_SECONDS,
            ) as connection:
                connection.sendall(b"zINSTREAM\0")
                for chunk in chunks:
                    connection.sendall(struct.pack("!I", len(chunk)))
                    connection.sendall(chunk)
                connection.sendall(struct.pack("!I", 0))
                response = bytearray()
                while data := connection.recv(4096):
                    response.extend(data)
                    if b"\0" in data:
                        break
        except OSError as exc:
            raise AntivirusUnavailable("ClamAV scan unavailable") from exc
        message = response.rstrip(b"\0\n").decode("utf-8", errors="replace")
        if message.endswith(" OK"):
            return AntivirusResult(clean=True)
        if message.endswith(" FOUND"):
            signature = message.rsplit(": ", 1)[-1].removesuffix(" FOUND")
            return AntivirusResult(clean=False, signature=signature[:128])
        raise AntivirusUnavailable("ClamAV returned an invalid response")
