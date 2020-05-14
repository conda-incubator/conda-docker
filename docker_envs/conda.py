import subprocess
import tempfile

from docker_envs.docker.base import Image


def conda_file_filter(
        trim_static_libs=True,
        trim_js_maps=True):

    def _tar_filter(tar_info):
        if trim_static_libs and tar_info.name.endswith('.a'):
            return None

        if trim_js_maps and tar_info.name.endswith('.js.map'):
            return None

        return tar_info

    return _tar_filter


def docker_environment(base_image, packages):
    with tempfile.TemporaryDirectory() as tmpdir:
        create(str(tmpdir), packages)

        images = Image.from_file(base_image)
        images[0].name = 'custom_conda_env'
        images[0].add_layer_path(
            str(tmpdir),
            filter=conda_file_filter())
        images[0].write_file(


def create(prefix, packages):
    subprocess.check_output(['conda', 'create', '-p', prefix] + list(packages))
