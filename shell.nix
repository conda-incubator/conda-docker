let
  pkgs = import (builtins.fetchTarball {
    url = "https://github.com/costrouc/nixpkgs/archive/37d3bd1af75a0e52a7e49262209b7762eb981832.tar.gz";
    sha256 = "12x7r0glbwi434b01d9992zz5nynz444jy056lqkaqb0fl8zij0a";
  }) {};

  pythonPackages = pkgs.python3Packages;
in
pkgs.mkShell {
  buildInputs = [ pkgs.python3 ];
}
