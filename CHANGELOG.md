=======================
conda-docker Change Log
=======================

<!-- current developments -->

## v0.1.1

**Fixed**

* Bug in `_precs_from_environment(...)` looks to be larger conda issues also simplified function in the process

## v0.1.0

**Changed:**

* Refactor docker logic into [python-docker](https://github.com/costrouc/python-docker) package for docker images building
* Decrease wordiness of conda-docker on builds
* Github-Actions for CI tests

**Fixed**

* Using `debian:sid-slim` as default base for docker images

**Authors**

* Chris Ostrouchov


## v0.0.3
**Changed:**

* `build_docker_environment` refactored into two functions to expose
  an internal function `build_docker_environment_image` to be used by
  libraries e.g. conda-store

**Fixed:**

* Use copies if conda installation and temporary directory are on different devices
* JSONDecodeError when using a list of package specification

**Authors:**

* Anthony Scopatz
* Chris Ostrouchov
* Chris Burr
* Julian Rüth



## v0.0.2
**Added:**

* Now implements a one-layer-per-package option. There is the 125 layer limit
  in docker, so for safety we only allow 100 individiual package layers. All
  packages after the initial 100 are combined into a single, last, squashed layer.
  The packages are installed in dependency order, so base-level packages are
  more likely to get their own layer and be reused. This is inspired by
  https://grahamc.com/blog/nix-and-layered-docker-images

**Authors:**

* Anthony Scopatz
* Chris Ostrouchov


**Added:**

* Adding support for setting docker v1 layer config e.g. ENV, LABEL, CMD, ENTRYPOINT etc.

## v0.0.1
**Added:**

* Initial release of `conda-docker`!

**Authors:**

* Anthony Scopatz


