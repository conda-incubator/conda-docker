import io
import tarfile
import secrets
from datetime import datetime, timezone

from docker_envs.docker.tar import (
    parse_v1, write_v1,
    write_tar_from_contents,
    write_tar_from_path
)


class Layer:
    def __init__(self, id, parent, architecture, os, created, author, checksum, size, content):
        self.created = created
        self.author = author
        self.id = id
        self.parent = parent
        self.architecture = architecture
        self.os = os
        self.size = size
        self.checksum = checksum
        self.content = content

    def list_files(self):
        tar = tarfile.TarFile(fileobj=io.BytesIO(self.content))
        return tar.getnames()


class Image:
    def __init__(self, name, tag, layers):
        self.name = name
        self.tag = tag
        self.layers = layers

    def remove_layer(self):
        self.layers.pop(0)

    def add_layer_path(self, path, recursive=True, filter=None):
        digest = write_tar_from_path(path, recursive=recursive, filter=filter)
        self._add_layer(digest)

    def add_layer_contents(self, contents):
        digest = write_tar_from_contents(contents)
        self._add_layer(digest)

    def _add_layer(self, digest):
        self.layers.insert(0, Layer(
            id=secrets.token_hex(32),
            parent=self.layers[0].id,
            architecture='amd64',
            os='linux',
            created=datetime.now(timezone.utc).astimezone().isoformat(),
            author='docker_envs',
            checksum=None,
            size=len(digest),
            content=digest))

    @staticmethod
    def from_file(filename):
        tar = tarfile.TarFile(filename)
        return parse_v1(tar)

    def write_file(self, filename, version='v1'):
        if version != 'v1':
            raise ValueError('only support writting v1 spec')

        write_v1(self, filename)
