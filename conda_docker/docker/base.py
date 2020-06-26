import io
import tarfile
import secrets
from datetime import datetime, timezone

from conda_docker import __version__ as VERSION
from conda_docker.docker.tar import (
    parse_v1,
    write_v1,
    write_tar_from_contents,
    write_tar_from_path,
    write_tar_from_paths,
)


class Layer:
    def __init__(
        self,
        id,
        parent,
        architecture,
        os,
        created,
        author,
        checksum,
        size,
        content,
        config=None,
    ):
        self.created = created
        self.author = author
        self.id = id
        self.parent = parent
        self.architecture = architecture
        self.os = os
        self.size = size
        self.checksum = checksum
        self.content = content
        self.config = config or {
            "Hostname": "",
            "Domainname": "",
            "User": "root",
            "AttachStdin": False,
            "AttachStdout": False,
            "AttachStderr": False,
            "Tty": False,
            "OpenStdin": False,
            "StdinOnce": False,
            "Env": [
                "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            ],
            "Cmd": ["/bin/bash"],
            "ArgsEscaped": True,
            "Image": "todo-implement",
            "Volumes": None,
            "WorkingDir": "",
            "Entrypoint": ["/bin/sh", "-c"],
            "OnBuild": None,
            "Labels": {"CONDA_DOCKER": VERSION,},
        }

    def list_files(self):
        tar = tarfile.TarFile(fileobj=io.BytesIO(self.content))
        return tar.getnames()


class Image:
    def __init__(self, name, tag, layers=None):
        self.name = name
        self.tag = tag
        self.layers = layers or []

    def remove_layer(self):
        self.layers.pop(0)

    def add_layer_path(
        self, path, arcpath=None, recursive=True, filter=None, base_id=None
    ):
        digest = write_tar_from_path(
            path, arcpath=arcpath, recursive=recursive, filter=filter
        )
        self._add_layer(digest, base_id=base_id)

    def add_layer_paths(self, paths, filter=None, base_id=None):
        digest = write_tar_from_paths(paths, filter=filter)
        self._add_layer(digest, base_id=base_id)

    def add_layer_contents(self, contents, filter=None, base_id=None):
        digest = write_tar_from_contents(contents, filter=filter)
        self._add_layer(digest, base_id=base_id)

    def _add_layer(self, digest, base_id=None):
        if len(self.layers) == 0:
            parent_id = None
        else:
            parent_id = self.layers[0].id
        layer_id = secrets.token_hex(32) if base_id is None else base_id

        layer = Layer(
            id=layer_id,
            parent=parent_id,
            architecture="amd64",
            os="linux",
            created=datetime.now(timezone.utc).astimezone().isoformat(),
            author="conda-docker",
            checksum=None,
            size=len(digest),
            content=digest,
        )

        self.layers.insert(0, layer)

    @staticmethod
    def from_file(filename):
        tar = tarfile.TarFile(filename)
        return parse_v1(tar)

    def write_file(self, filename, version="v1"):
        if version != "v1":
            raise ValueError("only support writting v1 spec")

        write_v1(self, filename)
