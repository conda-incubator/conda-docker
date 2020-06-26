import sys
import logging
import argparse

from conda_docker.conda import (
    build_docker_environment,
    find_user_conda,
    conda_info,
    find_precs,
    fetch_precs,
)
from conda_docker.logging import init_logging


def cli(args):
    parser = argparse.ArgumentParser(description="Docker Environments")
    subparsers = parser.add_subparsers()
    init_subcommand_build(subparsers)

    if len(args) == 0:
        parser.print_help()
        sys.exit(1)

    args = parser.parse_args(args)
    init_logging()
    args.func(args)


def init_subcommand_build(subparser):
    parser = subparser.add_parser("build", help="Docker Build Environment")
    parser.add_argument(
        "-b",
        "--base",
        type=str,
        # mimimal image with glibc
        default="frolvlad/alpine-glibc:latest",
        help="base image:tag to use for docker build",
    )
    parser.add_argument(
        "-i",
        "--image",
        type=str,
        default="conda-docker:latest",
        help="image:tag for output of docker envs build",
    )
    parser.add_argument(
        "-p", "--prefix", default=None, help="prefix path to build from", dest="prefix"
    )
    parser.add_argument(
        "-n", "--name", default=None, help="enviornment name to build from", dest="name"
    )
    parser.add_argument(
        "--conda-exe", default=None, help="path to conda executable", dest="conda_exe"
    )
    parser.add_argument(
        "-o", "--output", type=str, help="filename for docker image", required=True
    )
    parser.add_argument(
        "-s",
        "--solver",
        default=None,
        help="Which conda implementation to use as a solver. This will default to "
        "mamba (if available), and the user's conda otherwise.",
    )
    parser.add_argument(
        "--layering-strategy",
        dest="layering_strategy",
        default="layered",
        choices={"layered", "single"},
        help="The strategy to employ when adding layers to the image:\n"
        "* single: put all packages into a single layer\n"
        "* layered (default): try to place each package in its own layer.\n"
        "    noarch packages & leaf packages.",
    )
    parser.add_argument(
        "package_specs",
        nargs="*",
        help="packages specs to install in image if environment or prefix not given",
    )
    parser.set_defaults(func=handle_conda_build)


def handle_conda_build(args):
    user_conda = find_user_conda() if args.conda_exe is None else args.conda_exe
    info = conda_info(user_conda)
    platform = info["platform"]
    download_dir = info["pkgs_dirs"][0]
    default_prefix = info["default_prefix"]
    channels = info.get("channels", [])
    conda_default_channels = info.get("conda_default_channels", [])
    channels_remap = info.get("channels_remap", [])
    precs = find_precs(
        user_conda,
        download_dir,
        channels=channels,
        conda_default_channels=conda_default_channels,
        channels_remap=channels_remap,
        name=args.name,
        prefix=args.prefix,
        package_specs=args.package_specs,
        solver=args.solver,
    )
    records = fetch_precs(download_dir, precs)
    # now build image
    build_docker_environment(
        args.base,
        args.image,
        records,
        args.output,
        default_prefix,
        download_dir,
        user_conda,
        channels_remap,
        layering_strategy=args.layering_strategy,
    )


def main(args=None):
    args = sys.argv[1:] if args is None else args
    try:
        cli(args)
    except KeyboardInterrupt:
        logging.shutdown()
