import sys
import logging
import argparse

from conda_docker.conda import build_docker_environment
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
    parser.add_argument('-p', '--package', action='append', help='packages to install in image')
    parser.add_argument('-o', '--output', type=str, help='filename for docker image', required=True)
    parser.set_defaults(func=handle_conda_build)


def handle_conda_build(args):
    build_docker_environment(args.base, args.image, args.package, args.output)


def main(args=None):
    args = sys.argv[1:] if args is None else args
    try:
        cli(args)
    except KeyboardInterrupt:
        logging.shutdown()
