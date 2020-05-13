import tarfile
import hashlib
import json
import io


def _extract_file(tar, filename):
    f = tar.extractfile(filename)
    return f.read()

def _extract_json(tar, filename):
    f = _extract_file(tar, filename)
    return json.loads(f.decode('utf-8'))

def _add_file(tar, filename, content):
    tar_info = tarfile.TarInfo(name=filename)
    tar_info.size = len(content)
    content = io.BytesIO(content)
    content.seek(0)
    tar.addfile(tar_info, content)


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

    def list(self):
        tar = tarfile.TarFile(fileobj=io.BytesIO(self.content))
        return tar.getnames()

    def v1_json(self):
        keys = {
            'created', 'author', 'id', 'parent', 'architecture',
            'os', 'size', 'checksum'
        }

        return json.dumps(
            {k: getattr(self, k) for k in keys if getattr(self, k) is not None}
        ).encode('utf-8')


class Image:
    def __init__(self, name, tag, layers):
        self.name = name
        self.tag = tag
        self.layers = layers

    @staticmethod
    def _parse_v1_layer(tar, layer_id):
        d = _extract_json(tar, f'{layer_id}/json')
        content = _extract_file(tar, f'{layer_id}/layer.tar')
        return Layer(
            id=d['id'],
            parent=d.get('parent'),
            architecture=d.get('architecture'),
            os=d['os'],
            created=d['created'],
            author=d.get('author'),
            checksum=d.get('checksum'),
            size=d.get('size'),
            content=content
        )

    @staticmethod
    def parse_v1(cls, tar):
        d = _extract_json(tar, 'repositories')

        images = []
        for image_name, config in d.items():
            for image_tag, layer_id in config.items():
                current_layer = cls._parse_v1_layer(tar, layer_id)
                layers = [current_layer]
                while current_layer.parent is not None:
                    layer_id = current_layer.parent
                    current_layer = cls._parse_v1_layer(tar, layer_id)
                    layers.append(current_layer)

                images.append(cls(name=image_name, tag=image_tag, layers=layers))

        return images

    def v1_repositories(self):
        return json.dumps({self.name + 'test': {self.tag: self.layers[0].id}}).encode('utf-8')

    def remove_layer(self):
        self.layers.pop(0)

    def add_layer(self, root_path):
        content = io.BytesIO()
        with tarfile.TarFile(mode='w', fileobj=content) as tar:
            _add_file(tar, 'this/is/a/test', b'asdfasdfasdf')
        content.seek(0)
        content = content.getvalue()

        self.layers.insert(0, Layer(
            id="a9561eb1b190625c9adb5a9513e72c4dedafc1cb2d4c5236c9a6957ec7dfd5a9",
            parent=self.layers[0].id,
            architecture='amd64',
            os='linux',
            created='2014-10-13T21:19:18.674353812Z',
            author='Chris Ostrouchov',
            checksum=None,
            size=len(content),
            content=content))

    @classmethod
    def from_file(cls, filename):
        tar = tarfile.TarFile(filename)
        return cls.parse_v1(cls, tar)

    def write(self, filename):
        with tarfile.TarFile(filename, 'w') as tar:
            content = self.v1_repositories()
            _add_file(tar, 'repositories', content)

            for layer in self.layers:
                _add_file(tar, f'{layer.id}/VERSION', b'1.0')
                _add_file(tar, f'{layer.id}/layer.tar', layer.content)
                _add_file(tar, f'{layer.id}/json', layer.v1_json())
