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
from typing import List

from python_docker.base import Image
from python_docker.registry import Registry
from conda.exports import download

try:
    from conda import __version__ as CONDA_INTERFACE_VERSION

    conda_interface_type = "conda"
except ImportError:
    raise RuntimeError(
        "Conda must be installed for python interpreter\n"
        f"with sys.prefix: {sys.prefix}"
    )
from conda.models.channel import all_channel_urls

try:
    from conda.models.records import PackageCacheRecord
except ImportError:
    from conda.models.package_cache_record import PackageCacheRecord
from conda.models.dist import Dist

from conda_docker.utils import timer, md5_files, can_link


LOGGER = logging.getLogger(__name__)
CONDA_MAJOR_MINOR = tuple(int(x) for x in CONDA_INTERFACE_VERSION.split(".")[:2])


def conda_file_filter(trim_static_libs=True, trim_js_maps=True):
    def _tar_filter(tar_info):
        if trim_static_libs and tar_info.name.endswith(".a"):
            return None

        if trim_js_maps and tar_info.name.endswith(".js.map"):
            return None

        return tar_info

    return _tar_filter


def get_final_url(channels_remap, url):
    for entry in channels_remap:
        src = entry["src"]
        dst = entry["dest"]
        if url.startswith(src):
            new_url = url.replace(src, dst)
            if url.endswith(".tar.bz2"):
                print(
                    "WARNING: You need to make the package {} available "
                    "at {}".format(url.rsplit("/", 1)[1], new_url)
                )
            return new_url
    return url


def get_repodata(url):
    """Obtain the repodata from a channel URL"""
    if CONDA_MAJOR_MINOR >= (4, 5):
        from conda.core.subdir_data import fetch_repodata_remote_request

        raw_repodata_str = fetch_repodata_remote_request(url, None, None)
    elif CONDA_MAJOR_MINOR >= (4, 4):
        from conda.core.repodata import fetch_repodata_remote_request

        raw_repodata_str = fetch_repodata_remote_request(url, None, None)
    elif CONDA_MAJOR_MINOR >= (4, 3):
        from conda.core.repodata import fetch_repodata_remote_request

        repodata_obj = fetch_repodata_remote_request(None, url, None, None)
        raw_repodata_str = json.dumps(repodata_obj)
    else:
        raise NotImplementedError(
            f"unsupported version of conda: {CONDA_INTERFACE_VERSION}"
        )
    full_repodata = json.loads(raw_repodata_str)
    return full_repodata


def load_repodatas(
    download_dir, channels=(), conda_default_channels=(), channels_remap=()
):
    """Load all repodatas into a single dict"""
    cache_dir = os.path.join(download_dir, "cache")
    os.makedirs(cache_dir, exist_ok=True)

    remaps = {url["src"].rstrip("/"): url["dest"].rstrip("/") for url in channels_remap}
    urls = all_channel_urls(
        url.rstrip("/")
        for url in list(remaps) + list(channels) + list(conda_default_channels)
    )
    repodatas = {url: get_repodata(url) for url in urls}
    return repodatas


def get_dist_name(fn):
    """Returns the distname from the filename"""
    fn = os.path.basename(fn)
    if fn.endswith(".tar.bz2"):
        dist_name = fn[:-8]
    else:
        dist_name, _ = os.path.splitext(fn)
    return dist_name


def _precs_from_environment(environment, list_flag, download_dir, user_conda):
    explicit = subprocess.check_output(
        [user_conda, "list", list_flag, environment, "--explicit", "--json", "--md5"],
        encoding="utf-8",
        universal_newlines=True,
    )
    packages = []
    for line in explicit.splitlines():
        if not line or line.startswith("#") or line.startswith("@"):
            continue

        url, _, md5 = line.rpartition("#")
        _, _, fn = url.rpartition("/")

        dist = Dist.from_url(url)
        package_tarball_full_path = os.path.join(download_dir, fn)
        extracted_package_dir = os.path.join(download_dir, dist.dist_name)

        packages.append(
            PackageCacheRecord(
                url=url,
                md5=md5,
                fn=fn,
                package_tarball_full_path=package_tarball_full_path,
                extracted_package_dir=extracted_package_dir,
                channel=dist.channel,
                base_url=dist.base_url,
                build_number=dist.build_number,
                build_string=dist.build_string,
                subdir=dist.platform,
                name=dist.name,
                version=dist.version,
            )
        )
    
    pip_files = pip_precs_from_environment_prefix(environment)
    precs_dict = {"precs": packages, "pip_precs": pip_files, "env_path": environment}
    return precs_dict


def precs_from_environment_name(environment, download_dir, user_conda):
    return _precs_from_environment(environment, "--name", download_dir, user_conda)


def precs_from_environment_prefix(environment, download_dir, user_conda):
    return _precs_from_environment(environment, "--prefix", download_dir, user_conda)

def pip_precs_from_environment_prefix(environment):
    pip_freeze_output = subprocess.check_output(
        [f"{environment}/bin/python", "-m", "pip", "freeze"],
        encoding="utf-8",
        universal_newlines=True,
    )

    pip_package_metadatas = []
    for line in pip_freeze_output.splitlines():
        line_parts = line.split("==")
        if len(line_parts) == 2:
            package_name = line_parts[0]
            pip_package_metadatas.append(subprocess.check_output(
                [f"{environment}/bin/python", "-m", "pip", "show", "-f", package_name],
                encoding="utf-8",
                universal_newlines=True,
            ))

    # The output of `pip show -f package` looks something like:
    
    # Name: foopackage
    # Location: /opt/conda/envs/some_env/site-packages
    # Files:
    #   foopackage/__init__.py 
    #   foopackage/foo.py
    
    # We'll use this information to build a list of files to copy into the image.

    pip_files = []
    for metadata in pip_package_metadatas:
        pip_file_names = metadata.split("Files:\n")[-1].split('\n')
        pip_file_names_no_spaces = list(map(lambda path: path.lstrip(), pip_file_names))
        pip_file_names_no_cache = filter(lambda path: path and not path.endswith(".pyc"), pip_file_names_no_spaces)
        pip_path_prefix = metadata.split("Location: ")[1].split('\n')[0]
        pip_path_after_env = pip_path_prefix.split(environment)[1]

        pip_files += list(map(lambda path: os.path.join(pip_path_after_env, path), pip_file_names_no_cache))

    return pip_files

def precs_from_package_specs(
    package_specs,
    solver,
    download_dir,
    user_conda,
    channels=(),
    conda_default_channels=(),
    channels_remap=(),
):
    """Get the package records from a list of package names/specs, as you
    might type them in on the command line. This has to perform a solve.
    """
    # perform solve
    solver_conda = find_solver_conda(solver, user_conda)
    LOGGER.info("solving conda environment")
    with timer(
        LOGGER, "solving conda environment"
    ), tempfile.TemporaryDirectory() as tmpdir:
        # need temp env prefix, just in case.
        json_listing = subprocess.check_output(
            [
                solver_conda,
                "create",
                "--dry-run",
                "--prefix",
                os.path.join(tmpdir, "prefix"),
                "--json",
            ]
            + package_specs
        )
    listing = json.loads(json_listing)
    listing = listing["actions"]["LINK"]

    # get repodata so that we have the MD5 sums
    LOGGER.info("loading repodata")
    with timer(LOGGER, "loading repodata"):
        used_channels = {f"{x['base_url']}/{x['platform']}" for x in listing}
        repodatas = load_repodatas(
            download_dir,
            channels=used_channels,
            channels_remap=channels_remap,
        )

    # now, create PackageCacheRecords
    precs = []
    for package in listing:
        dist_name = package["dist_name"]
        fn = dist_name + ".tar.bz2"
        plat = package.pop("platform")
        channel = f"{package['base_url']}/{plat}"
        url = f"{channel}/{fn}"
        pkg_repodata = repodatas[channel]["packages"][fn]
        md5 = pkg_repodata["md5"]
        package_tarball_full_path = os.path.join(download_dir, fn)
        extracted_package_dir = os.path.join(download_dir, dist_name)
        precs.append(
            PackageCacheRecord(
                url=url,
                md5=md5,
                fn=fn,
                package_tarball_full_path=package_tarball_full_path,
                extracted_package_dir=extracted_package_dir,
                **package,
            )
        )
    return precs


def find_precs(
    user_conda,
    download_dir,
    name=None,
    prefix=None,
    package_specs=None,
    solver=None,
    channels=(),
    conda_default_channels=(),
    channels_remap=(),
):
    if name is not None:
        precs = precs_from_environment_name(name, download_dir, user_conda)
    elif prefix is not None:
        precs = precs_from_environment_prefix(prefix, download_dir, user_conda)
    elif package_specs is not None:
        precs = precs_from_package_specs(
            package_specs,
            solver,
            download_dir,
            user_conda,
            channels=channels,
            conda_default_channels=conda_default_channels,
            channels_remap=channels_remap,
        )
    else:
        raise RuntimeError("could not determine package list")
    return precs


def conda_info(user_conda):
    s = subprocess.check_output([user_conda, "info", "--json"])
    info = json.loads(s)
    return info


def find_user_conda(conda_exe="conda"):
    """Find the user's conda."""
    user_conda = os.environ.get("CONDA_EXE", "") or conda_exe
    return user_conda


def find_solver_conda(solver, user_conda):
    """Finds the right conda implementation to perform environment
    solves with.
    """
    if solver is not None:
        return solver
    mamba = shutil.which("mamba")
    return user_conda if mamba is None else os.path.expandvars(mamba)


def fetch_precs(download_dir, precs):
    os.makedirs(download_dir, exist_ok=True)

    non_pip_precs = precs["precs"]

    records = []
    for prec in non_pip_precs:
        package_tarball_full_path = os.path.join(download_dir, prec.fn)
        if package_tarball_full_path.endswith(".tar.bz2"):
            extracted_package_dir = package_tarball_full_path[:-8]
        elif package_tarball_full_path.endswith(".conda"):
            extracted_package_dir = package_tarball_full_path[:-6]

        if (
            os.path.isfile(package_tarball_full_path)
            and md5_files([package_tarball_full_path]) == prec.md5
        ):
            LOGGER.debug(f"already have: {prec.fn}")
        else:
            LOGGER.debug(f"fetching: {prec.fn}")
            download(prec.url, os.path.join(download_dir, prec.fn))

        if not os.path.isdir(extracted_package_dir):
            from conda.gateways.disk.create import extract_tarball

            extract_tarball(package_tarball_full_path, extracted_package_dir)

        repodata_record_path = os.path.join(
            extracted_package_dir, "info", "repodata_record.json"
        )

        with open(repodata_record_path, "w") as fh:
            json.dump(prec.dump(), fh, indent=2, sort_keys=True, separators=(",", ": "))

        package_cache_record = PackageCacheRecord.from_objects(
            prec,
            package_tarball_full_path=package_tarball_full_path,
            extracted_package_dir=extracted_package_dir,
        )
        records.append(package_cache_record)
        precs["precs"] = records
    return precs


def write_urls(records, host_pkgs_dir, channels_remap):
    lines = []
    for record in records:
        url = get_final_url(channels_remap, record.url)
        lines.append(f"{url}#{record.md5}")
    lines.append("\n")
    s = "\n".join(lines)

    fname = os.path.join(host_pkgs_dir, "urls")
    with open(fname, "w") as f:
        f.write(s)


def write_urls_txt(records, host_pkgs_dir, channels_remap):
    lines = [get_final_url(channels_remap, record.url) for record in records]
    lines.append("\n")
    s = "\n".join(lines)

    fname = os.path.join(host_pkgs_dir, "urls.txt")
    with open(fname, "w") as f:
        f.write(s)


def write_environments_txt(new_root):
    # this avoids a bug with not being able to write to the regsirty
    host_home_dotconda = os.path.join(new_root, "root", ".conda")
    os.makedirs(host_home_dotconda, exist_ok=True)
    with open(os.path.join(host_home_dotconda, "environments.txt"), "w") as f:
        f.write("/opt/conda\n")


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
    with open(host_history, "w") as f:
        f.write("\n".join(builder))


def write_repodata_records(download_dir, records, host_pkgs_dir, channels_remap):
    for record in records:
        fname = record.fn
        if fname.endswith(".conda"):
            distname = fname[:-6]
        elif fname.endswith(".tar.bz2"):
            distname = fname[:-8]
        record_file = os.path.join(distname, "info", "repodata_record.json")
        record_file_src = os.path.join(download_dir, record_file)

        with open(record_file_src, "r") as rf:
            rr_json = json.load(rf)

        rr_json["url"] = get_final_url(channels_remap, rr_json["url"])
        rr_json["channel"] = get_final_url(channels_remap, rr_json["channel"])

        os.makedirs(os.path.join(host_pkgs_dir, distname, "info"), exist_ok=True)
        record_file_dest = os.path.join(host_pkgs_dir, record_file)
        with open(record_file_dest, "w") as rf:
            json.dump(rr_json, rf, indent=2, sort_keys=True)


def chroot_install(
    new_root, records, orig_prefix, download_dir, user_conda, channels_remap
):
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
    host_standalone = os.path.join(new_root, "_conda.exe")
    os.makedirs(host_pkgs_dir, exist_ok=True)

    if can_link(orig_prefix, new_root):
        copy_func = os.link
    else:
        copy_func = shutil.copy

    copy_func(orig_standalone, host_standalone)

    # now link in pkgs
    targ_conda_opt = os.path.join("/opt", "conda")
    targ_pkgs_dir = os.path.join(targ_conda_opt, "pkgs")
    host_record_fns = []
    targ_record_fns = []
    for record in records:
        host_record_fn = os.path.join(host_pkgs_dir, record.fn)
        copy_func(record.package_tarball_full_path, host_record_fn)
        host_record_fns.append(host_record_fn)
        targ_record_fns.append(os.path.join(targ_pkgs_dir, record.fn))

    # write an environment file to install from
    s = "@EXPLICIT\nfile://" + "\nfile://".join(targ_record_fns) + "\n"
    host_env_txt = os.path.join(host_pkgs_dir, "env.txt")
    with open(host_env_txt, "w") as f:
        f.write(s)

    # set up host as base env
    write_environments_txt(new_root)
    write_urls(records, host_pkgs_dir, channels_remap)
    write_urls_txt(records, host_pkgs_dir, channels_remap)
    write_conda_meta(host_conda_opt, records, user_conda)
    write_repodata_records(download_dir, records, host_pkgs_dir, channels_remap)

    # copy in host bash
    host_bin = os.path.join(new_root, "bin")
    bin_tools = ["bash", "mv"]
    host_bin_tools = [os.path.join(host_bin, t) for t in bin_tools]
    os.makedirs(host_bin, exist_ok=True)
    for tool, host_tool in zip(bin_tools, host_bin_tools):
        shutil.copy2("/bin/" + tool, host_tool)

    # extract packages
    subprocess.check_call(
        [
            orig_standalone,
            "constructor",
            "--prefix",
            host_conda_opt,
            "--extract-conda-pkgs",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    # now install packages in chroot
    env = dict(os.environ)
    env["CONDA_SAFETY_CHECKS"] = "disabled"
    env["CONDA_EXTRA_SAFETY_CHECKS"] = "no"
    env["CONDA_PKGS_DIRS"] = "/opt/conda/pkgs"
    env["CONDA_ROOT"] = "/opt/conda"
    env["HOME"] = "/root"
    # FIXME: this should reall be check_output(), but chroot or fakechroot is
    # giving some weird segfault after the install command completes ¯\_(ツ)_/¯
    subprocess.call(
        [
            "fakechroot",
            "chroot",
            new_root,
            "/_conda.exe",
            "install",
            "--offline",
            "--file",
            "/opt/conda/pkgs/env.txt",
            "-y",
            "--prefix",
            "/opt/conda",
        ],
        env=env,
        cwd=host_conda_opt,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # clean up hard links
    os.remove(host_standalone)
    for host_record_fn in host_record_fns:
        os.remove(host_record_fn)
    os.remove(host_env_txt)
    for host_tool in host_bin_tools:
        os.remove(host_tool)
    os.rmdir(host_bin)

    # remove files outside of /opt/conda dir
    for entry in os.scandir(new_root):
        if entry.name == "opt":
            continue
        elif entry.is_file():
            os.remove(entry)
        else:
            shutil.rmtree(entry)


def add_single_conda_layer(image, hostpath, arcpath=None, filter=None):
    LOGGER.info("adding single conda environment layer")
    with timer(LOGGER, "adding single conda environment layer"):
        image.add_layer_path(hostpath, arcpath=arcpath, filter=filter)


def _paths_from_record(record, hostpath, meta, dist_name):
    # read normal files, given by package metadata
    host_conda_opt = os.path.join(hostpath, "opt", "conda")
    dist_path = os.path.join(host_conda_opt, "pkgs", dist_name)
    files = meta.get("files", [])
    paths = {os.path.join(host_conda_opt, f): "/opt/conda/" + f for f in files}
    paths.update({os.path.dirname(k): os.path.dirname(v) for k, v in paths.items()})
    # read package metadata
    paths[dist_path] = dist_path[len(hostpath) :]
    meta_path = os.path.join(host_conda_opt, "conda-meta", dist_name + ".json")
    paths[meta_path] = meta_path[len(hostpath) :]
    for root, dirnames, filenames in os.walk(dist_path):
        arcroot = root[len(hostpath) :]
        paths.update(
            {os.path.join(root, d): os.path.join(arcroot, d) for d in dirnames}
        )
        paths.update(
            {os.path.join(root, f): os.path.join(arcroot, f) for f in filenames}
        )
    return paths


def add_conda_package_layers(image, hostpath, arcpath=None, filter=None, records=None):
    LOGGER.info("adding conda environment in package layers")
    with timer(LOGGER, "adding conda environment in package layers"):
        counter = 0
        files_in_layers = set()
        for record in records:
            if counter > 100:
                break
            # read metadata for the package
            dist_name = get_dist_name(record.fn)
            meta_path = os.path.join(
                hostpath, "opt", "conda", "conda-meta", dist_name + ".json"
            )
            with open(meta_path) as f:
                meta = json.load(f)
            base_id = meta.get("sha256", meta.get("md5") + 32 * "0")
            # build layer, we need to use add_layer_paths() to deduplicate inodes,
            # i.e. properly capture hardlinks
            paths = _paths_from_record(record, hostpath, meta, dist_name)
            files_in_layers.update(paths.keys())
            image.add_layer_paths(paths, filter=filter, base_id=base_id)
            counter += 1

        # add remaining packages / files into a single layer
        paths = {}
        for root, dirnames, filenames in os.walk(hostpath):
            arcroot = root[len(hostpath) :]
            for name in dirnames + filenames:
                host_name = os.path.join(root, name)
                if host_name in files_in_layers:
                    continue
                paths[host_name] = os.path.join(arcroot, name)
        image.add_layer_paths(paths, filter=filter)


def add_conda_layers(
    image,
    hostpath,
    arcpath=None,
    filter=None,
    records=None,
    layering_strategy="layered",
):
    if layering_strategy == "single":
        add_single_conda_layer(image, hostpath, arcpath=arcpath, filter=filter)
    elif layering_strategy == "layered":
        add_conda_package_layers(
            image, hostpath, arcpath=arcpath, filter=filter, records=records
        )
    else:
        raise ValueError(f"layering strategy not recognized: {layering_strategy}")

    LOGGER.info(f"docker image {image.name}:{image.tag} has {len(image.layers)} layers")


def parse_image_name(name):
    parts = name.split(":")
    if len(parts) == 1:
        return parts[0], "latest"
    return parts


def pull_container_image(base_image: str):
    base_image_name, base_image_tag = parse_image_name(base_image)
    if base_image == "scratch":
        image = Image(name=base_image_name, tag=base_image_tag)
    else:
        LOGGER.info(f"pulling base image {base_image_name}:{base_image_tag}")
        with timer(LOGGER, "pulling base image"):
            registry = Registry(
                hostname=os.environ.get(
                    "CONDA_DOCKER_REGISTRY_URL", "https://registry-1.docker.io"
                ),
                username=os.environ.get("CONDA_DOCKER_REGISTRY_USERNAME"),
                password=os.environ.get("CONDA_DOCKER_REGISTRY_PASSWORD"),
            )
            image = registry.pull_image(base_image_name, base_image_tag)
    return image


def build_docker_environment(
    base_image: str,
    output_image: str,
    records,
    output_filename: str,
    default_prefix: str,
    download_dir: str,
    user_conda: str,
    channels_remap: List,
    layering_strategy: str = "layered",
):
    image = build_docker_environment_image(
        pull_container_image(base_image),
        output_image,
        records,
        default_prefix,
        download_dir,
        user_conda,
        channels_remap,
        layering_strategy,
    )

    LOGGER.info("writing docker file to filesystem")
    with timer(LOGGER, "writing docker file"):
        image.write_filename(output_filename)

def copy_pip_packages(pip_targ_dir, pip_env, pip_files):
    for pip_file in pip_files:
        # Preserve the original pip file paths from the download dir to the target dir
        # by concatenating the start of the target dir with the end of source file path
        # (essentially just switching the source prefix with the target prefix)
        pip_path_source = os.path.join(pip_env, pip_file[1:]) # /opt/conda/envs/test/path_to_file/file_name
        if os.path.isfile(pip_path_source):
            pip_path_target = os.path.join(pip_targ_dir, pip_file[1:pip_file.rindex('/')]) # /tmp/tmpzlujmuh3/opt/conda/path_to_file
            if not os.path.isdir(pip_path_target):
                os.makedirs(pip_path_target)
            shutil.copy(pip_path_source, pip_path_target)

def build_docker_environment_image(
    base_image: Image,
    output_image,
    records,
    default_prefix,
    download_dir,
    user_conda,
    channels_remap,
    layering_strategy="layered",
):
    output_image_name, output_image_tag = parse_image_name(output_image)
    base_image.name = output_image_name
    base_image.tag = output_image_tag

    non_pip_packages = records["precs"]
    pip_file_paths = records["pip_precs"]
    env_path = records["env_path"]

    with tempfile.TemporaryDirectory() as tmpdir:
        LOGGER.info("building conda environment")

        with timer(LOGGER, "building conda environment"):
            chroot_install(
                str(tmpdir),
                non_pip_packages,
                default_prefix,
                download_dir,
                user_conda,
                channels_remap,
            )

            pip_targ_dir = os.path.join(str(tmpdir), "opt", "conda")

            copy_pip_packages(
                pip_targ_dir,
                env_path,
                pip_file_paths,
            )
        
        add_conda_layers(
            base_image,
            str(tmpdir),
            arcpath="/",
            filter=conda_file_filter(),
            records=non_pip_packages,
            layering_strategy=layering_strategy,
        )
        add_single_conda_layer(
            base_image,
            pip_targ_dir,
        )

        return base_image
