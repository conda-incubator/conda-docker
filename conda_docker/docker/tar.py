import io
import json
import tarfile


def _extract_file(tar, filename):
    f = tar.extractfile(filename)
    return f.read()


def _extract_json(tar, filename):
    f = _extract_file(tar, filename)
    return json.loads(f.decode("utf-8"))


def _add_file(tar, filename, content, filter=None):
    tar_info = tarfile.TarInfo(name=filename)
    tar_info.size = len(content)
    if filter is not None:
        tar_info = filter(tar_info)
        if tar_info is None:
            return
    content = io.BytesIO(content)
    content.seek(0)
    tar.addfile(tar_info, content)


def _parse_v1_layer(tar, layer_id):
    from conda_docker.docker.base import Layer

    d = _extract_json(tar, f"{layer_id}/json")
    content = _extract_file(tar, f"{layer_id}/layer.tar")
    return Layer(
        id=d["id"],
        parent=d.get("parent"),
        architecture=d.get("architecture"),
        os=d["os"],
        created=d["created"],
        author=d.get("author"),
        checksum=d.get("checksum"),
        size=d.get("size"),
        config=d.get("config"),
        content=content,
    )


def parse_v1(tar):
    from conda_docker.docker.base import Image

    d = _extract_json(tar, "repositories")

    images = []
    for image_name, config in d.items():
        for image_tag, layer_id in config.items():
            current_layer = _parse_v1_layer(tar, layer_id)
            layers = [current_layer]
            while current_layer.parent is not None:
                layer_id = current_layer.parent
                current_layer = _parse_v1_layer(tar, layer_id)
                layers.append(current_layer)

            images.append(Image(name=image_name, tag=image_tag, layers=layers))

    return images


def write_v1(image, filename):
    with tarfile.TarFile(filename, "w") as tar:
        content = write_v1_repositories(image)
        _add_file(tar, "repositories", content)

        for layer in image.layers:
            _add_file(tar, f"{layer.id}/VERSION", b"1.0")
            _add_file(tar, f"{layer.id}/layer.tar", layer.content)
            _add_file(tar, f"{layer.id}/json", write_v1_layer_metadata(layer))


def write_v1_layer_metadata(layer):
    keys = {
        "created",
        "author",
        "id",
        "parent",
        "architecture",
        "os",
        "size",
        "checksum",
    }

    metadata = {k: getattr(layer, k) for k in keys if getattr(layer, k) is not None}
    metadata["config"] = layer.config
    metadata["container_config"] = layer.config
    return json.dumps(metadata).encode("utf-8")


def write_v1_repositories(image):
    return json.dumps({image.name: {image.tag: image.layers[0].id}}).encode("utf-8")


def write_tar_from_contents(contents, filter=None):
    """Writes a tar file from a dict of archive names to bytes that represent the
    contents of each file.
    """
    digest = io.BytesIO()
    with tarfile.TarFile(mode="w", fileobj=digest) as tar:
        for filename, content in contents.items():
            _add_file(tar, filename, content, filter=filter)
    digest.seek(0)
    return digest.getvalue()


def write_tar_from_paths(paths, filter=None):
    """Writes a tar file from a dict mapping host name paths to
    archive names.
    """
    digest = io.BytesIO()
    with tarfile.TarFile(mode="w", fileobj=digest) as tar:
        for path, arcpath in paths.items():
            tar.add(path, arcname=arcpath, recursive=False, filter=filter)
    digest.seek(0)
    return digest.getvalue()


def write_tar_from_path(path, arcpath=None, recursive=True, filter=None):
    """Writes a tar file from a single path."""
    digest = io.BytesIO()
    with tarfile.TarFile(mode="w", fileobj=digest) as tar:
        tar.add(path, arcname=arcpath, recursive=recursive, filter=filter)
    digest.seek(0)
    return digest.getvalue()
