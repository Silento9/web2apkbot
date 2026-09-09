import ipaddress, socket
from urllib.parse import urlparse
import httpx

def validate_url(value: str) -> str:
    value = value.strip()
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("Only valid HTTP/HTTPS URLs are allowed.")

    host = parsed.hostname.lower().rstrip(".")
    if host in {"localhost", "localhost.localdomain"}:
        raise ValueError("Localhost URLs are not allowed.")

    try:
        infos = socket.getaddrinfo(host, None)
        for info in infos:
            ip = ipaddress.ip_address(info[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
                raise ValueError("Private or local network targets are not allowed.")
    except socket.gaierror:
        raise ValueError("Domain could not be resolved.")

    return value

async def check_url(url: str):
    url = validate_url(url)
    async with httpx.AsyncClient(
        timeout=15,
        follow_redirects=True,
        headers={"User-Agent": "Web2APK/1.0"}
    ) as client:
        response = await client.head(url)
        if response.status_code >= 500:
            raise ValueError("Website is currently unavailable.")
    return url
