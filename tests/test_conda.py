import os

import pytest

from conda_docker.conda import (
    build_docker_environment_image,
    pull_container_image,
    find_user_conda,
    conda_info,
    find_precs,
    fetch_precs,
)


skip_if_conda_build = pytest.mark.skipif(
    os.environ.get("CONDA_BUILD", "") == "1", reason="In conda-build"
)


class CondaMakeData:
    """Needed to store state between tests"""

    user_conda = default_prefix = None
    download_dir = precs = records = None
    base_image = None


@skip_if_conda_build
@pytest.mark.incremental
class TestCondaMake:
    def test_find_precs(self, class_tmpdir):
        CondaMakeData.user_conda = find_user_conda()
        info = conda_info(CondaMakeData.user_conda)
        CondaMakeData.download_dir = class_tmpdir / "pkgs"
        channels = info.get("channels", [])
        CondaMakeData.default_prefix = info["default_prefix"]
        precs = find_precs(
            CondaMakeData.user_conda,
            CondaMakeData.download_dir,
            channels=channels,
            package_specs=["make"],
            solver=CondaMakeData.user_conda,
        )
        names = {pr.name for pr in precs}
        assert "make" in names
        CondaMakeData.precs = precs

    def test_fetch_precs(self):
        records = fetch_precs(CondaMakeData.download_dir, CondaMakeData.precs)
        names = {r.name for r in records}
        assert "make" in names
        CondaMakeData.records = records

    def test_build_docker_environment(self, class_tmpdir):
        image = build_docker_environment_image(
            pull_container_image("library/debian:sid-slim"),
            "example:test",
            CondaMakeData.records,
            CondaMakeData.default_prefix,
            CondaMakeData.download_dir,
            CondaMakeData.user_conda,
            [],  # channels_remap
        )
        assert image.name == "example"
        assert image.tag == "test"
        assert len(image.layers) > 2
