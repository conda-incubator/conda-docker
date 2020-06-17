from urllib.request import Request, urlopen
import json
import tarfile
import io
import gzip

from conda_docker.docker.base import Image, Layer


def get_request(url, headers=None):
    headers = headers or {}

    request = Request(url)
    for key, value in headers.items():
        request.add_header(key, value)

    return urlopen(request).read()


def get_token(scope="repository:library/ubuntu:pull"):
    url = f"https://auth.docker.io/token?service=registry.docker.io&scope={scope}"
    return json.loads(get_request(url).decode("utf-8"))["token"]


def get_manifest(image, tag, token):
    headers = {"Authorization": f"Bearer {token}"}

    url = f"https://registry-1.docker.io/v2/{image}/manifests/{tag}"
    return json.loads(get_request(url, headers).decode("utf-8"))


def get_blob(image, blobsum, token):
    headers = {"Authorization": f"Bearer {token}"}

    url = f"https://registry-1.docker.io/v2/{image}/blobs/{blobsum}"
    return gzip.decompress(get_request(url, headers))


def pull_image(image, tag):
    token = get_token(scope=f"repository:{image}:pull")
    manifest = get_manifest(image, tag, token)

    layers = []
    for metadata, blob in zip(manifest["history"], manifest["fsLayers"]):
        d = json.loads(metadata["v1Compatibility"])
        digest = get_blob(image, blob["blobSum"], token)
        layers.append(
            Layer(
                id=d["id"],
                parent=d.get("parent"),
                architecture=d.get("architecture"),
                os=d.get("os"),
                created=d["created"],
                author=d.get("author"),
                checksum=d.get("checksum"),
                size=d.get("size"),
                config=d.get("config"),
                content=digest,
            )
        )
    return Image(image, tag, layers)
