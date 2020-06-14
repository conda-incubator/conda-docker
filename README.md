Conda Docker
============

Conda Docker is an extension to the docker concept by having declarative
environments that are associated with docker images. In addition this
tool does not require docker to build images. Thus allowing for
interesting caching behavior and tricks that docker would not normally
allow.

Features:

-   `docker` is not needed to build images
-   declarative environments that map 1:1 to docker images
-   significantly faster build times since builds can take advantage of
    package cache
-   interesting opportunities for layering (e.g. mkl gets separate
    layer)
-   no dependencies allowing for library packaged as
    [zipapp](https://docs.python.org/3/library/zipapp.html)

References
----------

-   [Docker Registry API
    Specification](https://docs.docker.com/registry/spec/api/)
-   Docker Image Specification
    -   [Summary](https://github.com/moby/moby/blob/master/image/spec/v1.2.md)
    -   [Registry V2
        Specification](https://docs.docker.com/registry/spec/manifest-v2-2/)

Examples using Library
----------------------

Downloading docker images without docker!

``` python
from docker_envs.registry.client import pull_image

image = pull_image('frolvlad/alpine-glibc', 'latest')
```

Modify docker image from filesystem

``` {.python results="output"}
from docker_envs.docker.base import Image
from docker_envs.registry.client import pull_image
from docker_envs.conda import conda_file_filter

image = pull_image('continuumio/miniconda3', 'latest')
image.remove_layer()
image.name = 'this-is-a-test'
image.add_layer_path('./', filter=conda_file_filter())
image.add_layer_contents({
    'this/is/a/test1': b'this is test 1',
    'this/is/a/test2': b'this is test 2'
})
image.write_file('example-filter.tar')
```

Build conda docker image from library

``` {.python}
from docker_envs.conda import build_docker_environment

build_docker_environment(
    base_image='continuumio/miniconda3:latest',
    output_image='example-image:123456',
    packages=[
        'numpy',
        'numba',
        'flask',
    ],
    output_filename='demo.tar')
```

Build conda docker image from command line

``` {.shell}
# docker_envs.pyz # if you have it packaged as zipapp
python -m docker_envs build -b continuumio/miniconda3:latest \
                            -i example-image:123456 \
                            -p numpy -p numba -p flask \
                            -o demo.tar
```

How does this work?
-------------------

Turns out that docker images are just a tar collection of files. There
are several versions of the spec. For `v1.0` the specification is
\[[defined
here](https://github.com/moby/moby/blob/master/image/spec/v1.md).
Instead of writing down the spec lets look into a single docker image.

``` {.shell results="none"}
docker pull ubuntu:latest
docker save ubuntu:latest -o /tmp/ubuntu.tar
```

List the directory structure of the docker image. Notice how it is a
collection of `layer.tar` which is a tar archive of filesystems. And
several json files. `VERSION` file is always `1.0` currently.

``` {.shell results="output"}
tar -tvf /tmp/ubuntu.tar
```

Dockerhub happens to export docker images in a `v1` - `v1.2` compatible
format. Lets only look at the files important for `v1`. Repositories
tells the layer to use as the layer head of the current name/tag.

``` {.shell dir="/tmp" var="filename=\"repositories\"" results="output"}
tar -xf /tmp/ubuntu.tar $filename
cat $filename | python -m json.tool
```

For each layer there are three files: `VERSION`, `layer.tar`, and
`json`.

``` {.shell dir="/tmp" var="filename=\"93935bf1450219e4351893e546b97b4584083b01d19daeba56cab906fc75fc1c/VERSION\"" results="output"}
tar -xf /tmp/ubuntu.tar $filename
cat $filename
```

``` {.shell dir="/tmp" var="filename=\"93935bf1450219e4351893e546b97b4584083b01d19daeba56cab906fc75fc1c/json\"" results="output"}
tar -xf /tmp/ubuntu.tar $filename
cat $filename | python -m json.tool
```

Looking at layer metadata.

``` {.example}
{
    "id": "93935bf1450219e4351893e546b97b4584083b01d19daeba56cab906fc75fc1c",
    "created": "1969-12-31T19:00:00-05:00",
    "container_config": {
        "Hostname": "",
        "Domainname": "",
        "User": "",
        "AttachStdin": false,
        "AttachStdout": false,
        "AttachStderr": false,
        "Tty": false,
        "OpenStdin": false,
        "StdinOnce": false,
        "Env": null,
        "Cmd": null,
        "Image": "",
        "Volumes": null,
        "WorkingDir": "",
        "Entrypoint": null,
        "OnBuild": null,
        "Labels": null
    },
    "os": "linux"
}
```

Looking at the layer filesystem.

``` {.shell dir="/tmp" var="filename=\"93935bf1450219e4351893e546b97b4584083b01d19daeba56cab906fc75fc1c/layer.tar\"" results="output"}
tar -xf /tmp/ubuntu.tar $filename
tar -tvf $filename | head
```
