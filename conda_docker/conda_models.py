"""Substitute containers for conda information"""
# Significant portions of this file were originally forked from conda
# (c) 2016 Anaconda, Inc. / https://anaconda.com
# constructor is distributed under the terms of the BSD 3-clause license.
import os
import sys
import struct
import platform
from collections import OrderedDict

from toolz import unique, concat, concatv
from urllib3.util.url import Url

from .download import join_url, path_to_url, split_scheme_auth_token, urlparse


ON_WIN = bool(sys.platform == "win32")
DEFAULT_CUSTOM_CHANNELS = {
    "pkgs/pro": "https://repo.anaconda.com",
}
DEFAULT_CHANNEL_ALIAS = "https://conda.anaconda.org"
DEFAULT_CHANNELS_UNIX = (
    "https://repo.anaconda.com/pkgs/main",
    "https://repo.anaconda.com/pkgs/r",
)
DEFAULT_CHANNELS_WIN = (
    "https://repo.anaconda.com/pkgs/main",
    "https://repo.anaconda.com/pkgs/r",
    "https://repo.anaconda.com/pkgs/msys2",
)
DEFAULT_CHANNELS = DEFAULT_CHANNELS_WIN if ON_WIN else DEFAULT_CHANNELS_UNIX
DEFAULTS_CHANNEL_NAME = "defaults"
UNKNOWN_CHANNEL = "<unknown>"
_PLATFORM_MAP = {
    "linux2": "linux",
    "linux": "linux",
    "darwin": "osx",
    "win32": "win",
    "zos": "zos",
}
NON_X86_LINUX_MACHINES = frozenset(
    {"armv6l", "armv7l", "aarch64", "ppc64", "ppc64le", "s390x",}
)


def path_expand(path):
    return os.path.abspath(os.path.expanduser(os.path.expandvars(path)))


def conda_in_private_env():
    """Is conda located in its own private environment named '_conda_'"""
    envs_dir, env_name = os.path.split(sys.prefix)
    return env_name == "_conda_" and os.path.basename(envs_dir) == "envs"


class Context:
    """Context stub"""

    def __init__(
        self,
        subdir=None,
        default_channels=None,
        restore_free_channel=False,
        croot="",
        bld_path="",
        root_prefix="",
        force_32bit=False,
        channel_alias=DEFAULT_CHANNEL_ALIAS,
        custom_channels=None,
        migrated_channel_aliases=(),
        allow_non_channel_urls=False,
    ):
        self._subdir = subdir
        self._default_channels = (
            DEFAULT_CHANNELS if default_channels is None else default_channels
        )
        self._custom_multichannels = {}
        self._croot = croot
        self._root_prefix = root_prefix
        self.bld_path = bld_path
        self.restore_free_channel = restore_free_channel
        self.force_32bit = force_32bit
        self._channel_alias = channel_alias
        self._channel_alias_obj = None
        self._custom_channels = (
            DEFAULT_CUSTOM_CHANNELS if custom_channels is None else custom_channels
        )
        self._custom_channels_obj = None
        self._migrated_channel_aliases = migrated_channel_aliases
        self.allow_non_channel_urls = allow_non_channel_urls

    @property
    def subdir(self):
        if self._subdir:
            return self._subdir
        m = platform.machine()
        if m in NON_X86_LINUX_MACHINES:
            self._subdir = f"linux-{m}"
        elif self.platform == "zos":
            self._subdir = "zos-z"
        else:
            self._subdir = f"{self.platform}-{self.bits}"
        return self._subdir

    @property
    def subdirs(self):
        return (self.subdir, "noarch")

    @property
    def root_prefix(self):
        if self._root_prefix:
            return os.path.abspath(os.path.expanduser(self._root_prefix))
        elif conda_in_private_env():
            return os.path.abspath(os.path.join(self.conda_prefix, "..", ".."))
        else:
            return self.conda_prefix

    @property
    def conda_prefix(self):
        return os.path.abspath(sys.prefix)

    @property
    def conda_build_local_paths(self):
        # does file system reads to make sure paths actually exist
        return tuple(
            unique(
                full_path
                for full_path in (
                    path_expand(d)
                    for d in (
                        self._croot,
                        self.bld_path,
                        # self.conda_build.get('root-dir'),  # not doing it this way
                        os.path.join(self.root_prefix, "conda-bld"),
                        "~/conda-bld",
                    )
                    if d
                )
                if os.path.isdir(full_path)
            )
        )

    @property
    def conda_build_local_urls(self):
        return tuple(map(path_to_url, self.conda_build_local_paths))

    @property
    def custom_multichannels(self):
        if self._custom_multichannels:
            return self._custom_multichannels
        default_channels = list(self._default_channels)
        if self.restore_free_channel:
            default_channels.insert(1, "https://repo.anaconda.com/pkgs/free")

        reserved_multichannel_urls = OrderedDict(
            (
                (DEFAULTS_CHANNEL_NAME, default_channels),
                ("local", self.conda_build_local_urls),
            )
        )
        reserved_multichannels = OrderedDict(
            (
                name,
                tuple(
                    Channel.make_simple_channel(self.channel_alias, url) for url in urls
                ),
            )
            for name, urls in reserved_multichannel_urls.items()
        )
        custom_multichannels = OrderedDict(
            (
                name,
                tuple(
                    Channel.make_simple_channel(self.channel_alias, url) for url in urls
                ),
            )
            for name, urls in self._custom_multichannels.items()
        )
        all_multichannels = OrderedDict(
            (name, channels)
            for name, channels in concat(
                map(
                    list,
                    (
                        custom_multichannels.items(),
                        reserved_multichannels.items(),  # reserved comes last, so reserved overrides custom
                    ),
                )
            )
        )
        self._custom_multichannels = all_multichannels
        return all_multichannels

    @property
    def custom_channels(self):
        if self._custom_channels_obj is not None:
            return self._custom_channels_obj
        custom_channels = (
            Channel.make_simple_channel(self.channel_alias, url, name)
            for name, url in self._custom_channels.items()
        )
        channels_from_multichannels = concat(
            channel for channel in self.custom_multichannels.values()
        )
        all_channels = OrderedDict(
            (x.name, x)
            for x in (
                ch for ch in concatv(channels_from_multichannels, custom_channels,)
            )
        )
        self._custom_channels_obj = all_channels
        return self._custom_channels_obj

    @property
    def platform(self):
        return _PLATFORM_MAP.get(sys.platform, "unknown")

    @property
    def bits(self):
        if self.force_32bit:
            return 32
        else:
            return 8 * struct.calcsize("P")

    @property
    def channel_alias(self):
        if self._channel_alias_obj is not None:
            return self._channel_alias_obj
        location, scheme, auth, token = split_scheme_auth_token(self._channel_alias)
        self._channel_alias_obj = Channel(
            scheme=scheme, auth=auth, location=location, token=token
        )
        return self._channel_alias_obj

    @property
    def migrated_channel_aliases(self):
        return tuple(
            Channel(scheme=scheme, auth=auth, location=location, token=token)
            for location, scheme, auth, token in (
                split_scheme_auth_token(c) for c in self._migrated_channel_aliases
            )
        )


class Channel:
    """Channel stub"""

    def __init__(
        self,
        scheme=None,
        auth=None,
        location=None,
        token=None,
        name=None,
        platform=None,
        package_filename=None,
        context=None,
    ):
        self.scheme = scheme
        self.auth = auth
        self.location = location
        self.token = token
        self.name = name
        self.platform = platform
        self.package_filename = package_filename
        self.context = context

    @property
    def canonical_name(self):
        if hasattr(self, "__canonical_name"):
            return self.__canonical_name

        context = self.context
        for multiname, channels in context.custom_multichannels.items():
            for channel in channels:
                if self.name == channel.name:
                    cn = self.__canonical_name = multiname
                    return cn

        for that_name in context.custom_channels:
            if self.name and tokenized_startswith(
                self.name.split("/"), that_name.split("/")
            ):
                cn = self.__canonical_name = self.name
                return cn

        if any(
            c.location == self.location
            for c in concatv(
                (context.channel_alias,), context.migrated_channel_aliases,
            )
        ):
            cn = self.__canonical_name = self.name
            return cn

        # fall back to the equivalent of self.base_url
        # re-defining here because base_url for MultiChannel is None
        if self.scheme:
            cn = self.__canonical_name = "%s://%s" % (
                self.scheme,
                join_url(self.location, self.name),
            )
            return cn
        else:
            cn = self.__canonical_name = join_url(self.location, self.name).lstrip("/")
            return cn

    def urls(self, with_credentials=False, subdirs=None):
        if subdirs is None:
            subdirs = self.context.subdirs

        if self.canonical_name == UNKNOWN_CHANNEL:
            return Channel(DEFAULTS_CHANNEL_NAME).urls(
                with_credentials=with_credentials, subdirs=subdirs
            )

        base = [self.location]
        if with_credentials and self.token:
            base.extend(["t", self.token])
        base.append(self.name)
        base = join_url(*base)

        def _platforms():
            if self.platform:
                yield self.platform
                if self.platform != "noarch":
                    yield "noarch"
            else:
                for subdir in subdirs:
                    yield subdir

        bases = (join_url(base, p) for p in _platforms())

        if with_credentials and self.auth:
            return ["%s://%s@%s" % (self.scheme, self.auth, b) for b in bases]
        else:
            return ["%s://%s" % (self.scheme, b) for b in bases]

    @staticmethod
    def make_simple_channel(channel_alias, channel_url, name=None):
        ca = channel_alias
        test_url, scheme, auth, token = split_scheme_auth_token(channel_url)
        if name and scheme:
            return Channel(
                scheme=scheme,
                auth=auth,
                location=test_url,
                token=token,
                name=name.strip("/"),
            )
        if scheme:
            if ca.location and test_url.startswith(ca.location):
                location, name = ca.location, test_url.replace(ca.location, "", 1)
            else:
                url_parts = urlparse(test_url)
                location = Url(host=url_parts.host, port=url_parts.port).url
                name = url_parts.path or ""
            return Channel(
                scheme=scheme,
                auth=auth,
                location=location,
                token=token,
                name=name.strip("/"),
            )
        else:
            return Channel(
                scheme=ca.scheme,
                auth=ca.auth,
                location=ca.location,
                token=ca.token,
                name=name and name.strip("/") or channel_url.strip("/"),
            )


def all_channel_urls(channels, subdirs=None, with_credentials=True, context=None):
    """Finds channel URLs"""
    result = set()
    for chn in channels:
        channel = Channel(chn, context=context)
        result.update(channel.urls(with_credentials, subdirs))
    return result


class PackageRecord:
    """PackageRecord stub"""

    def __init__(self, url=None, md5=None, fn=None):
        self.md5 = md5
        self.url = url
        self.fn = fn


class PackageCacheRecord(PackageRecord):
    """PackageCacheRecord stub"""

    def __init__(
        self, package_tarball_full_path=None, extracted_package_dir=None, **kwargs
    ):
        super().__init__(**kwargs)
        self.package_tarball_full_path = package_tarball_full_path
        self.extracted_package_dir = extracted_package_dir


class Dist:
    """Distribution stub"""

    def __init__(self, channel, dist_name=None, url=None):
        self.channel = channel
        self.dist_name = dist_name
        self.url = url

    @property
    def full_name(self):
        return self.__str__()

    def __str__(self):
        return f"{self.channel}::{self.dist_name}" if self.channel else self.dist_name
