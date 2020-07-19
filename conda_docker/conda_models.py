"""Substitute containers for conda information"""
# Significant portions of this file were originally forked from conda
# (c) 2016 Anaconda, Inc. / https://anaconda.com
# constructor is distributed under the terms of the BSD 3-clause license.
import os
import re
import sys
import struct
import platform
from collections import OrderedDict

from toolz import unique, concat, concatv
from urllib3.util.url import Url

from .download import (
    join_url,
    path_to_url,
    split_scheme_auth_token,
    urlparse,
    split_anaconda_token,
)


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
KNOWN_SUBDIRS = PLATFORM_DIRECTORIES = (
    "noarch",
    "linux-32",
    "linux-64",
    "linux-aarch64",
    "linux-armv6l",
    "linux-armv7l",
    "linux-ppc64",
    "linux-ppc64le",
    "linux-s390x",
    "osx-64",
    "win-32",
    "win-64",
    "zos-z",
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
        migrated_custom_channels=None,
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
        self.migrated_custom_channels = (
            {} if migrated_custom_channels is None else migrated_custom_channels
        )
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
    def known_subdirs(self):
        return frozenset(concatv(KNOWN_SUBDIRS, self.subdirs))

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


RE_HAS_SCHEME = re.compile(r"[a-z][a-z0-9]{0,11}://")


def has_scheme(value):
    """Returns scheme"""
    return RE_HAS_SCHEME.match(value)


RE_WIN_PATH_BACKOUT = re.compile(r"(\\(?! ))")


def win_path_backout(path):
    """Replace all backslashes except those escaping spaces
    if we pass a file url, something like file://\\unc\path\on\win, make sure
    we clean that up too
    """
    return RE_WIN_PATH_BACKOUT.sub(r"/", path).replace(":////", "://")


def _split_platform_re(known_subdirs):
    _platform_match_regex = r"/(%s)(?:/|$)" % r"|".join(
        r"%s" % d for d in known_subdirs
    )
    return re.compile(_platform_match_regex, re.IGNORECASE)


def split_platform(known_subdirs, url):
    """
    Examples:
        >>> from conda.base.constants import KNOWN_SUBDIRS
        >>> split_platform(KNOWN_SUBDIRS, "https://1.2.3.4/t/tk-123/linux-ppc64le/path")
        (u'https://1.2.3.4/t/tk-123/path', u'linux-ppc64le')
    """
    _platform_match = _split_platform_re(known_subdirs).search(url)
    platform = _platform_match.groups()[0] if _platform_match else None
    cleaned_url = url.replace("/" + platform, "", 1) if platform is not None else url
    return cleaned_url.rstrip("/"), platform


def strip_pkg_extension(path):
    """
    Examples:
        >>> strip_pkg_extension("/path/_license-1.1-py27_1.tar.bz2")
        ('/path/_license-1.1-py27_1', '.tar.bz2')
        >>> strip_pkg_extension("/path/_license-1.1-py27_1.conda")
        ('/path/_license-1.1-py27_1', '.conda')
        >>> strip_pkg_extension("/path/_license-1.1-py27_1")
        ('/path/_license-1.1-py27_1', None)
    """
    # NOTE: not using CONDA_TARBALL_EXTENSION_V1 or CONDA_TARBALL_EXTENSION_V2 to comply with
    #       import rules and to avoid a global lookup.
    if path[-6:] == ".conda":
        return path[:-6], ".conda"
    elif path[-8:] == ".tar.bz2":
        return path[:-8], ".tar.bz2"
    elif path[-5:] == ".json":
        return path[:-5], ".json"
    else:
        return path, None


def split_conda_url_easy_parts(known_subdirs, url):
    # scheme, auth, token, platform, package_filename, host, port, path, query
    cleaned_url, token = split_anaconda_token(url)
    cleaned_url, platform = split_platform(known_subdirs, cleaned_url)
    _, ext = strip_pkg_extension(cleaned_url)
    cleaned_url, package_filename = (
        cleaned_url.rsplit("/", 1) if ext else (cleaned_url, None)
    )
    url_parts = urlparse(cleaned_url)
    return (
        url_parts.scheme,
        url_parts.auth,
        token,
        platform,
        package_filename,
        url_parts.host,
        url_parts.port,
        url_parts.path,
        url_parts.query,
    )


def tokenized_startswith(test_iterable, startswith_iterable):
    return all(t == sw for t, sw in zip(test_iterable, startswith_iterable))


def tokenized_conda_url_startswith(test_url, startswith_url):
    test_url, startswith_url = urlparse(test_url), urlparse(startswith_url)
    if test_url.host != startswith_url.host or test_url.port != startswith_url.port:
        return False
    norm_url_path = lambda url: url.path.strip("/") or "/"
    return tokenized_startswith(
        norm_url_path(test_url).split("/"), norm_url_path(startswith_url).split("/")
    )


def _read_channel_configuration(scheme, host, port, path, context=None):
    # return location, name, scheme, auth, token
    path = path and path.rstrip("/")
    test_url = Url(host=host, port=port, path=path).url

    # Step 1. No path given; channel name is None
    if not path:
        return (
            Url(host=host, port=port).url.rstrip("/"),
            None,
            scheme or None,
            None,
            None,
        )

    # Step 2. migrated_custom_channels matches
    for name, location in sorted(
        context.migrated_custom_channels.items(), reverse=True, key=lambda x: len(x[0])
    ):
        location, _scheme, _auth, _token = split_scheme_auth_token(location)
        if tokenized_conda_url_startswith(test_url, join_url(location, name)):
            # translate location to new location, with new credentials
            subname = test_url.replace(join_url(location, name), "", 1).strip("/")
            channel_name = join_url(name, subname)
            channel = _get_channel_for_name(channel_name)
            return (
                channel.location,
                channel_name,
                channel.scheme,
                channel.auth,
                channel.token,
            )

    # Step 3. migrated_channel_aliases matches
    for migrated_alias in context.migrated_channel_aliases:
        if test_url.startswith(migrated_alias.location):
            name = test_url.replace(migrated_alias.location, "", 1).strip("/")
            ca = context.channel_alias
            return ca.location, name, ca.scheme, ca.auth, ca.token

    # Step 4. custom_channels matches
    for name, channel in sorted(
        context.custom_channels.items(), reverse=True, key=lambda x: len(x[0])
    ):
        that_test_url = join_url(channel.location, channel.name)
        if tokenized_startswith(test_url.split("/"), that_test_url.split("/")):
            subname = test_url.replace(that_test_url, "", 1).strip("/")
            return (
                channel.location,
                join_url(channel.name, subname),
                scheme,
                channel.auth,
                channel.token,
            )

    # Step 5. channel_alias match
    ca = context.channel_alias
    if ca.location and tokenized_startswith(
        test_url.split("/"), ca.location.split("/")
    ):
        name = test_url.replace(ca.location, "", 1).strip("/") or None
        return ca.location, name, scheme, ca.auth, ca.token

    # Step 6. not-otherwise-specified file://-type urls
    if host is None:
        # this should probably only happen with a file:// type url
        assert port is None
        location, name = test_url.rsplit("/", 1)
        if not location:
            location = "/"
        _scheme, _auth, _token = "file", None, None
        return location, name, _scheme, _auth, _token

    # Step 7. fall through to host:port as channel_location and path as channel_name
    #  but bump the first token of paths starting with /conda for compatibility with
    #  Anaconda Enterprise Repository software.
    bump = None
    path_parts = path.strip("/").split("/")
    if path_parts and path_parts[0] == "conda":
        bump, path = "conda", "/".join(drop(1, path_parts))
    return (
        Url(host=host, port=port, path=bump).url.rstrip("/"),
        path.strip("/") or None,
        scheme or None,
        None,
        None,
    )


def parse_conda_channel_url(url, context=None):
    """Parses conda URLs"""
    (
        scheme,
        auth,
        token,
        platform,
        package_filename,
        host,
        port,
        path,
        query,
    ) = split_conda_url_easy_parts(context.known_subdirs, url)
    # recombine host, port, path to get a channel_name and channel_location
    (
        channel_location,
        channel_name,
        configured_scheme,
        configured_auth,
        configured_token,
    ) = _read_channel_configuration(scheme, host, port, path, context=context)
    return Channel(
        configured_scheme or "https",
        auth or configured_auth,
        channel_location,
        token or configured_token,
        channel_name,
        platform,
        package_filename,
        context=context,
    )


RE_PATH_MATCH = re.compile(
    r"\./"  # ./
    r"|\.\."  # ..
    r"|~"  # ~
    r"|/"  # /
    r"|[a-zA-Z]:[/\\]"  # drive letter, colon, forward or backslash
    r"|\\\\"  # windows UNC path
    r"|//"  # windows UNC path
)


def is_path(value):
    if "://" in value:
        return False
    return RE_PATH_MATCH.match(value)


def is_package_file(path):
    """
    Examples:
        >>> is_package_file("/path/_license-1.1-py27_1.tar.bz2")
        True
        >>> is_package_file("/path/_license-1.1-py27_1.conda")
        True
        >>> is_package_file("/path/_license-1.1-py27_1")
        False
    """
    # NOTE: not using CONDA_TARBALL_EXTENSION_V1 or CONDA_TARBALL_EXTENSION_V2 to comply with
    #       import rules and to avoid a global lookup.
    return path[-6:] == ".conda" or path[-8:] == ".tar.bz2"


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
    def from_url(url, context=None):
        return parse_conda_channel_url(url, context=context)

    @staticmethod
    def from_value(value, context=None):
        if value in (None, "<unknown>", "None:///<unknown>", "None"):
            return Channel(name=UNKNOWN_CHANNEL, context=context)
        value = str(value)
        if has_scheme(value):
            if value.startswith("file:"):
                value = win_path_backout(value)
            return Channel.from_url(value, context=context)
        elif is_path(value):
            return Channel.from_url(path_to_url(value), context=context)
        elif is_package_file(value):
            if value.startswith("file:"):
                value = win_path_backout(value)
            return Channel.from_url(value, context=context)
        else:
            # at this point assume we don't have a bare (non-scheme) url
            #   e.g. this would be bad:  repo.anaconda.com/pkgs/free
            _stripped, platform = split_platform(value, context.known_subdirs)
            if _stripped in context.custom_multichannels:
                return MultiChannel(
                    _stripped,
                    context.custom_multichannels[_stripped],
                    platform,
                    context=context,
                )
            else:
                return Channel.from_channel_name(value, context=context)

    @staticmethod
    def make_simple_channel(channel_alias, channel_url, name=None, context=None):
        ca = channel_alias
        test_url, scheme, auth, token = split_scheme_auth_token(channel_url)
        if name and scheme:
            return Channel(
                scheme=scheme,
                auth=auth,
                location=test_url,
                token=token,
                name=name.strip("/"),
                context=context,
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
                context=context,
            )
        else:
            return Channel(
                scheme=ca.scheme,
                auth=ca.auth,
                location=ca.location,
                token=ca.token,
                name=name and name.strip("/") or channel_url.strip("/"),
                context=context,
            )


class MultiChannel(Channel):
    def __init__(self, name, channels, platform=None, context=None):
        self.name = name
        self.location = None

        if platform:
            c_dicts = tuple(c.dump() for c in channels)
            any(cd.update(platform=platform) for cd in c_dicts)
            self._channels = tuple(Channel(context=context, **cd) for cd in c_dicts)
        else:
            self._channels = channels

        self.scheme = None
        self.auth = None
        self.token = None
        self.platform = platform
        self.package_filename = None

    @property
    def channel_location(self):
        return self.location

    @property
    def canonical_name(self):
        return self.name

    def urls(self, with_credentials=False, subdirs=None):
        from itertools import chain

        _channels = self._channels
        return list(
            chain.from_iterable(c.urls(with_credentials, subdirs) for c in _channels)
        )

    @property
    def base_url(self):
        return None

    @property
    def base_urls(self):
        return tuple(c.base_url for c in self._channels)

    def url(self, with_credentials=False):
        return None

    def dump(self):
        return {"name": self.name, "channels": tuple(c.dump() for c in self._channels)}


def all_channel_urls(channels, subdirs=None, with_credentials=True, context=None):
    """Finds channel URLs"""
    result = set()
    for chn in channels:
        channel = Channel.from_value(chn, context=context)
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
