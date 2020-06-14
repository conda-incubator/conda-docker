"""Interface for finding, grabbing, and installing conda pakcages into docker image"""
# Significant portions of this file were originally forked from conda constuctor
# (c) 2016 Anaconda, Inc. / https://anaconda.com
# constructor is distributed under the terms of the BSD 3-clause license.
import os
import sys
import json
import time
import shutil
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
from conda.models.dist import Dist

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


def get_final_url(channels_remap, url):
    for entry in channels_remap:
        src = entry['src']
        dst = entry['dest']
        if url.startswith(src):
            new_url = url.replace(src, dst)
            if url.endswith(".tar.bz2"):
              print("WARNING: You need to make the package {} available "
                    "at {}".format(url.rsplit('/', 1)[1], new_url))
            return new_url
    return url


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
            logger.info(f'already have: {prec.fn}')
        else:
            logger.info(f'fetching: {prec.fn}')
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
    urls = {r.url for r in precs}
    return tuple(r for r in pc.iter_records() if r.url in urls)


def write_urls(records, host_pkgs_dir, channels_remap):
    lines = []
    for record in records:
        url = get_final_url(channels_remap, record.url)
        lines.append(f"{url}#{record.md5}")
    lines.append("\n")
    s = "\n".join(lines)

    fname = os.path.join(host_pkgs_dir, "urls")
    with open(fname, 'w') as f:
        f.write(s)


def write_urls_txt(records, host_pkgs_dir, channels_remap):
    lines = [get_final_url(channels_remap, record.url) for record in records]
    lines.append("\n")
    s = "\n".join(lines)

    fname = os.path.join(host_pkgs_dir, "urls.txt")
    with open(fname, 'w') as f:
        f.write(s)


def write_conda_meta(host_conda_opt, records, user_conda):
    cmd = os.path.split(user_conda)[-1]
    if len(sys.argv) > 1:
        cmd = f"{cmd} {' '.join(sys.argv[1:])}"

    builder = [
        f"==> {time.strftime('%Y-%m-%d %H:%M:%S')} <==",
        f"# cmd: {cmd}",
    ]
    dists = tuple(Dist(r.url) for r in records)

    builder.extend(f"+{dist.full_name}" for dist in dists)
    builder.append("\n")

    host_conda_meta = os.path.join(host_conda_opt, "conda-meta")
    host_history = os.path.join(host_conda_meta, "history")
    os.makedirs(host_conda_meta, exist_ok=True)
    with open(host_history, 'w') as f:
        f.write("\n".join(builder))


def write_repodata_records(download_dir, records, host_pkgs_dir, channels_remap):
    for record in records:
        fname = record.fn
        if fname.endswith(".conda"):
            distname = fname[:-6]
        elif fname.endswith(".tar.bz2"):
            distname = fname[:-8]
        record_file = os.path.join(distname, 'info', 'repodata_record.json')
        record_file_src = os.path.join(download_dir, record_file)

        with open(record_file_src, 'r') as rf:
            rr_json = json.load(rf)

        rr_json['url'] = get_final_url(channels_remap, rr_json['url'])
        rr_json['channel'] = get_final_url(channels_remap, rr_json['channel'])

        os.makedirs(os.path.join(host_pkgs_dir, distname, 'info'), exist_ok=True)
        record_file_dest = os.path.join(host_pkgs_dir, record_file)
        with open(record_file_dest, 'w') as rf:
            json.dump(rr_json, rf, indent=2, sort_keys=True)


def chroot_install(new_root, records, orig_prefix, download_dir, user_conda, channels_remap):
    """Installs conda packages into a new root environment"""
    # Some terminology:
    #   orig - the conda directory / environment we are copying from
    #          This is the normal user's conda prefix, path, etc
    #   host - this is path on the user's machine OUTSIDE of the chroot
    #          This is normally a temp directory, and prefixed by new_root
    #   targ - This is the path INSIDE of the chroot, ie host minus the new_root
    # first, link conda standalone into chroot dir
    host_conda_opt = os.path.join(new_root, "opt", "conda")
    host_pkgs_dir = os.path.join(host_conda_opt, "pkgs")
    orig_standalone = os.path.join(orig_prefix, "standalone_conda", "conda.exe")
    host_standalone = os.path.join(host_conda_opt, "_conda.exe")
    os.makedirs(host_pkgs_dir, exist_ok=True)
    os.link(orig_standalone, host_standalone)

    # now link in pkgs
    targ_conda_opt = os.path.join("/opt", "conda")
    targ_pkgs_dir = os.path.join(targ_conda_opt, "pkgs")
    host_record_fns = []
    targ_record_fns = []
    for record in records:
        host_record_fn = os.path.join(host_pkgs_dir, record.fn)
        os.link(record.package_tarball_full_path, host_record_fn)
        host_record_fns.append(host_record_fn)
        targ_record_fns.append(os.path.join(targ_pkgs_dir, record.fn))

    # write an environment file to install from
    s = "@EXPLICIT\nfile:/" + "\nfile:/".join(targ_record_fns) + "\n"
    host_env_txt = os.path.join(host_pkgs_dir, "env.txt")
    with open(host_env_txt, 'w') as f:
        f.write(s)

    # set up host as base env
    write_urls(records, host_pkgs_dir, channels_remap)
    write_urls_txt(records, host_pkgs_dir, channels_remap)
    write_conda_meta(host_conda_opt, records, user_conda)
    write_repodata_records(download_dir, records, host_pkgs_dir, channels_remap)

    # now install packages in chroot
    subprocess.check_output(
        [orig_standalone, "constructor", "--prefix", host_conda_opt, "--extract-conda-pkgs"]
    )
    #import pdb; pdb.set_trace()
    try:
        subprocess.check_output([
            "fakechroot",
            "chroot", new_root, "/opt/conda/_conda.exe", "install", "--offline",
            "--file", "/opt/conda/pkgs/env.txt", "-yp", "/opt/conda",
        ]
        )
    except:
        print("new_root", new_root)
        import pdb; pdb.set_trace()

    # clean up hard links
    os.remove(host_standalone)
    for host_record_fn in host_record_fns:
        os.remove(host_record_fn)
    os.remove(host_env_txt)


def build_docker_environment(base_image, output_image, records, output_filename,
        default_prefix, download_dir, user_conda, channels_remap
    ):
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
            chroot_install(str(tmpdir), records, default_prefix, download_dir,
                user_conda, channels_remap)

        logger.info(f'adding conda environment layer')
        with timer(logger, 'adding conda environment layer'):
            image.add_layer_path(str(tmpdir), filter=conda_file_filter())

        logger.info(f'writing docker file to filesystem')
        with timer(logger, 'writing docker file'):
            image.write_file(output_filename)


def create(prefix, packages):
    subprocess.check_output(['conda', 'create', '-y', '-p', prefix] + list(packages))
