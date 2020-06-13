import sys
import logging

from conda_docker.cli import cli


def main():
    try:
        cli(sys.argv[1:])
    except KeyboardInterrupt:
        logging.shutdown()


if __name__ == "__main__":
    main()
