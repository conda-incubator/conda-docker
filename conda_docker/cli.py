import sys
import logging
import argparse

from conda_docker.conda import (
    build_docker_environment, find_user_conda, conda_info, find_precs,
    fetch_precs,
)
from conda_docker.logging import init_logging


def cli(args):
    parser = argparse.ArgumentParser(description='Docker Environments')
    subparsers = parser.add_subparsers()
    init_subcommand_build(subparsers)

    if len(args) == 0:
        parser.print_help()
        sys.exit(1)

    args = parser.parse_args(args)
    init_logging()
    args.func(args)


def init_subcommand_build(subparser):
    parser = subparser.add_parser('build', help='Docker Build Environment')
    parser.add_argument('-b', '--base', type=str, default='continuumio/miniconda3:latest', help='base image:tag to use for docker build')
    parser.add_argument('-i', '--image', type=str, default='conda_docker:latest', help='image:tag for output of docker envs build')
    #parser.add_argument('-p', '--package', action='append', help='packages to install in image')
    parser.add_argument('-p', '--prefix', default=None, help='prefix path to build from', dest="prefix")
    parser.add_argument('-n', '--name', default=None, help='enviornment name to build from', dest="name")
    parser.add_argument('--conda-exe', default=None, help="path to conda executable", dest="conda_exe")
    parser.add_argument('-o', '--output', type=str, help='filename for docker image', required=True)
    parser.set_defaults(func=handle_conda_build)


def handle_conda_build(args):
    user_conda = find_user_conda() if args.conda_exe is None else args.conda_exe
    info = conda_info(user_conda)
    download_dir = info["pkgs_dirs"][0]
    default_prefix = info["default_prefix"]
    channels_remap = info.get('channels_remap', [])
    precs = find_precs(user_conda, download_dir, name=args.name, prefix=args.prefix)
    records = fetch_precs(download_dir, precs)
    # sort records in dependency order, as given by precs
    rd = {r.name: r for r in records}
    records = tuple([rd[r.name] for r in precs])
    # now build image
    build_docker_environment(args.base, args.image, records, args.output, default_prefix,
        download_dir, user_conda, channels_remap)


def main(args=None):
    args = sys.argv[1:] if args is None else args
    try:
        cli(args)
    except KeyboardInterrupt:
        logging.shutdown()
