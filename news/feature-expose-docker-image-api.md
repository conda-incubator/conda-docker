**Changed:**

* `build_docker_environment` refactored into two functions to expose
  an internal function `build_docker_environment_image` to be used by
  libraries e.g. conda-store
