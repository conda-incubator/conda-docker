import subprocess
import tempfile
import logging

from docker_envs.docker.base import Image
from docker_envs.registry.client import pull_image

logger = logging.getLogger(__name__)


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


def build_docker_environment(base_image, output_image, packages, output_filename):
    def parse_image_name(name):
        parts = name.split(':')
        if len(parts) == 1:
            return parts[0], 'latest'
        return parts

    base_image_name, base_image_tag = parse_image_name(base_image)
    output_image_name, output_image_tag = parse_image_name(output_image)

    with tempfile.TemporaryDirectory() as tmpdir:
        if base_image == 'scratch':
            image = Image(name=output_image_name, tag=output_image_tag)
        else:
            logger.info(f'pulling base image {base_image_name}:{base_image_tag}')
            image = pull_image(base_image_name, base_image_tag)
            image.name = output_image_name
            image.tag = output_image_tag

        logger.info('building conda environment')
        create(str(tmpdir), packages)

        logger.info(f'adding conda environment layer')
        image.add_layer_path(str(tmpdir), filter=conda_file_filter())

        logger.info(f'writing docker file to filesystem')
        image.write_file(output_filename)


def create(prefix, packages):
    subprocess.check_output(['conda', 'create', '-y', '-p', prefix] + list(packages))
