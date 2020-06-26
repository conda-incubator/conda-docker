**Added:**

* Now implements a one-layer-per-package option. There is the 125 layer limit
  in docker, so for safety we only allow 100 individiual package layers. All
  packages after the initial 100 are combined into a single, last, squashed layer.
  The packages are installed in dependency order, so base-level packages are
  more likely to get their own layer and be reused. This is inspired by
  https://grahamc.com/blog/nix-and-layered-docker-images

**Changed:**

* <news item>

**Deprecated:**

* <news item>

**Removed:**

* <news item>

**Fixed:**

* <news item>

**Security:**

* <news item>
