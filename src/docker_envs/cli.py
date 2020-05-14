import argparse
import sys


from docker_envs.conda import build_docker_environment
from docker_envs.logging import init_logging


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
    parser.add_argument('-b', '--base', type=str, default='continuumio/minconda3:lastet', help='base image:tag to use for docker build')
    parser.add_argument('-i', '--image', type=str, default='docker_envs:latest', help='image:tag for output of docker envs build')
    parser.add_argument('-p', '--package', action='append', help='packages to install in image')
    parser.add_argument('-o', '--output', type=str, help='filename for docker image')
    parser.set_defaults(func=handle_conda_build)


def handle_conda_build(args):
    build_docker_environment(args.base, args.image, args.package, args.output)
