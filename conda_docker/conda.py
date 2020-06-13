"""Interface for finding, grabbing, and installing conda pakcages into docker image"""
# Significant portions of this file were originally forked from conda constuctor
# (c) 2016 Anaconda, Inc. / https://anaconda.com
# constructor is distributed under the terms of the BSD 3-clause license.
import os
import sys
import json
import logging
import tempfile
import subprocess

from conda.api import PackageCacheData
from conda.exports import download
from conda.core.package_cache_data import PackageCacheData
try:
    from conda.models.records import PackageCacheRecord
except ImportError:
    from conda.models.package_cache_record import PackageCacheRecord

from conda_docker.docker.base import Image
from conda_docker.registry.client import pull_image
from conda_docker.utils import timer, md5_files


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


def _precs_from_environment(environment, list_flag, download_dir, user_conda):
    # get basic data about the environment's packages
    json_listing = subprocess.check_output([user_conda, "list", list_flag, environment, "--json"])
    listing = json.loads(json_listing)
    packages = {p["dist_name"]: p for p in listing}
    # get the package install order and MD5 sums,
    # creating a tuple of dist_name, URL, MD5, filename (fn)
    explicit = subprocess.check_output([user_conda, "list", list_flag, environment,
                                        "--explicit", "--json", "--md5"],
                                        universal_newlines=True)
    ordering = []
    for line in explicit.splitlines():
        if not line or line.startswith("#") or line.startswith("@"):
            continue
        url, _, md5 = line.rpartition("#")
        _, _, fn = url.rpartition("/")
        if fn.endswith(".tar.bz2"):
            dist_name = fn[:-8]
        else:
            dist_name, _ = splitext(fn)
        ordering.append((dist_name, url, md5, fn))

    # now, create PackageCacheRecords
    precs = []
    for dist_name, url, md5, fn in ordering:
        package = packages[dist_name]
        platform_arch = package.pop("platform")
        package_tarball_full_path = os.path.join(download_dir, fn)
        extracted_package_dir = os.path.join(download_dir, dist_name)
        precs.append(PackageCacheRecord(url=url, md5=md5, fn=fn,
            package_tarball_full_path=package_tarball_full_path,
            extracted_package_dir=extracted_package_dir,
            **package))
    return precs


def precs_from_environment_name(environment, download_dir, user_conda):
    return _precs_from_environment(environment, "--name", download_dir, user_conda)


def precs_from_environment_prefix(environment, download_dir, user_conda):
    return _precs_from_environment(environment, "--prefix", download_dir, user_conda)


def find_precs(user_conda, download_dir, name=None, prefix=None):
    if name is not None:
        precs = precs_from_environment_name(name, download_dir, user_conda)
    elif prefix is not None:
        precs = precs_from_environment_prefix(prefix, download_dir, user_conda)
    else:
        raise RuntimeError("could not determine package list")
    return precs


def conda_info(user_conda):
    s = subprocess.check_output([user_conda, "info", "--json"])
    info = json.loads(s)
    return info


def find_user_conda(conda_exe="conda"):
    user_conda = os.environ.get('CONDA_EXE', '') or conda_exe
    return user_conda


def fetch_precs(download_dir, precs):
    os.makedirs(download_dir, exist_ok=True)
    pc = PackageCacheData(download_dir)

    for prec in precs:
        package_tarball_full_path = os.path.join(download_dir, prec.fn)
        if package_tarball_full_path.endswith(".tar.bz2"):
            extracted_package_dir = package_tarball_full_path[:-8]
        elif package_tarball_full_path.endswith(".conda"):
            extracted_package_dir = package_tarball_full_path[:-6]

        if (os.path.isfile(package_tarball_full_path)
            and md5_files([package_tarball_full_path]) == prec.md5):
            print('already have: {0}'.format(prec.fn), file=sys.stderr)
        else:
            print('fetching: {0}'.format(prec.fn), file=sys.stderr)
            download(prec.url, os.path.join(download_dir, prec.fn))

        if not os.path.isdir(extracted_package_dir):
            from conda.gateways.disk.create import extract_tarball
            extract_tarball(package_tarball_full_path, extracted_package_dir)

        repodata_record_path = os.path.join(extracted_package_dir, 'info', 'repodata_record.json')

        with open(repodata_record_path, "w") as fh:
            json.dump(prec.dump(), fh, indent=2, sort_keys=True, separators=(',', ': '))

        package_cache_record = PackageCacheRecord.from_objects(
            prec,
            package_tarball_full_path=package_tarball_full_path,
            extracted_package_dir=extracted_package_dir,
        )
        pc.insert(package_cache_record)

    return tuple(pc.iter_records())


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
            with timer(logger, 'pulling base image'):
                image = pull_image(base_image_name, base_image_tag)
                image.name = output_image_name
                image.tag = output_image_tag

        logger.info('building conda environment')
        with timer(logger, 'building conda environment'):
            create(str(tmpdir), packages)

        logger.info(f'adding conda environment layer')
        with timer(logger, 'adding conda environment layer'):
            image.add_layer_path(str(tmpdir), filter=conda_file_filter())

        logger.info(f'writing docker file to filesystem')
        with timer(logger, 'writing docker file'):
            image.write_file(output_filename)


#def create(prefix, packages):
#    subprocess.check_output(['conda', 'create', '-y', '-p', prefix] + list(packages))
