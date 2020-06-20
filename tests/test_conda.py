import pytest

from conda_docker.conda import (
    build_docker_environment,
    find_user_conda,
    conda_info,
    find_precs,
    fetch_precs,
)


class CondaMakeData:
    """Needed to store state between tests"""
    user_conda = default_prefix = None
    download_dir = precs = records = None



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
        )
        names = {pr.name for pr in precs}
        assert "make" in names
        CondaMakeData.precs = precs

    def test_fetch_precs(self):
        records = fetch_precs(CondaMakeData.download_dir, CondaMakeData.precs)
        names = {r.name for r in records}
        assert "make" in names
        CondaMakeData.records = records

    def test_build_docker_environment(self):
        build_docker_environment(
            "frolvlad/alpine-glibc:latest",
            "example:test",
            CondaMakeData.records,
            "test.tar",
            CondaMakeData.default_prefix,
            CondaMakeData.download_dir,
            CondaMakeData.user_conda,
            [],  # channels_remap
        )
