import httpx


def contains_secret(value: object, secret: str) -> bool:
    if isinstance(value, str):
        return secret in value
    if isinstance(value, dict):
        return any(
            contains_secret(key, secret) or contains_secret(item, secret)
            for key, item in value.items()
        )
    if isinstance(value, (list, tuple)):
        return any(contains_secret(item, secret) for item in value)
    return False


async def bounded_response_body(response: httpx.Response, max_bytes: int) -> bytes | None:
    declared = response.headers.get("Content-Length")
    if declared is not None:
        try:
            if int(declared) < 0 or int(declared) > max_bytes:
                return None
        except ValueError:
            return None
    body = bytearray()
    async for chunk in response.aiter_bytes():
        body.extend(chunk)
        if len(body) > max_bytes:
            return None
    return bytes(body)
