"""Tools for downloading URLs"""
# -*- coding: utf-8 -*-
# Originally forked from conda
# Copyright (C) 2012 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
import hashlib
import logging
import tempfile
import warnings
import sys
import os
import re
import shutil
import ctypes
from ctypes.util import find_library

import requests
from requests import ConnectionError, HTTPError
from requests.packages.urllib3.exceptions import InsecureRequestWarning
from requests.exceptions import (
    InvalidSchema,
    SSLError,
    ProxyError as RequestsProxyError,
)
from urllib3.util.url import Url, parse_url


LOGGER = logging.getLogger(__name__)
ON_WIN = bool(sys.platform == "win32")


def join_url(*args):
    """Joins URL parts into a single string"""
    start = '/' if not args[0] or args[0].startswith('/') else ''
    return start + '/'.join(y for y in (x.strip('/') for x in args if x) if y)


def path_to_url(path):
    if not path:
        raise ValueError('Not allowed: %r' % path)
    if path.startswith(file_scheme):
        try:
            path.decode('ascii')
        except UnicodeDecodeError:
            raise ValueError('Non-ascii not allowed for things claiming to be URLs: %r' % path)
        return path
    path = os.path.abspath(os.path.expanduser(path)).replace('\\', '/')
    # We do not use urljoin here because we want to take our own
    # *very* explicit control of how paths get encoded into URLs.
    #   We should not follow any RFCs on how to encode and decode
    # them, we just need to make sure we can represent them in a
    # way that will not cause problems for whatever amount of
    # urllib processing we *do* need to do on them (which should
    # be none anyway, but I doubt that is the case). I have gone
    # for ASCII and % encoding of everything not alphanumeric or
    # not in `!'()*-._/:`. This should be pretty save.
    #
    # To avoid risking breaking the internet, this code only runs
    # for `file://` URLs.
    #
    percent_encode_chars = "!'()*-._/\\:"
    percent_encode = lambda s: "".join(["%%%02X" % ord(c), c]
                                       [c < "{" and c.isalnum() or c in percent_encode_chars]
                                       for c in s)
    if any(ord(char) >= 128 for char in path):
        path = percent_encode(path.decode('unicode-escape')
                              if hasattr(path, 'decode')
                              else bytes(path, "utf-8").decode('unicode-escape'))

    # https://blogs.msdn.microsoft.com/ie/2006/12/06/file-uris-in-windows/
    if len(path) > 1 and path[1] == ':':
        path = file_scheme + '/' + path
    else:
        path = file_scheme + path
    return path


def urlparse(url):
    if ON_WIN and url.startswith('file:'):
        url.replace('\\', '/')
    return parse_url(url)


_ANACONDA_TOKEN_RE = re.compile(r'/t/([a-zA-Z0-9-]*)')

def split_anaconda_token(url):
    """
    Examples:
        >>> split_anaconda_token("https://1.2.3.4/t/tk-123-456/path")
        (u'https://1.2.3.4/path', u'tk-123-456')
        >>> split_anaconda_token("https://1.2.3.4/t//path")
        (u'https://1.2.3.4/path', u'')
        >>> split_anaconda_token("https://some.domain/api/t/tk-123-456/path")
        (u'https://some.domain/api/path', u'tk-123-456')
        >>> split_anaconda_token("https://1.2.3.4/conda/t/tk-123-456/path")
        (u'https://1.2.3.4/conda/path', u'tk-123-456')
        >>> split_anaconda_token("https://1.2.3.4/path")
        (u'https://1.2.3.4/path', None)
        >>> split_anaconda_token("https://10.2.3.4:8080/conda/t/tk-123-45")
        (u'https://10.2.3.4:8080/conda', u'tk-123-45')
    """
    _token_match = _ANACONDA_TOKEN_RE.search(url)
    token = _token_match.groups()[0] if _token_match else None
    cleaned_url = url.replace('/t/' + token, '', 1) if token is not None else url
    return cleaned_url.rstrip('/'), token


def split_scheme_auth_token(url):
    """
    Examples:
        >>> split_scheme_auth_token("https://u:p@conda.io/t/x1029384756/more/path")
        ('conda.io/more/path', 'https', 'u:p', 'x1029384756')
        >>> split_scheme_auth_token(None)
        (None, None, None, None)
    """
    if not url:
        return None, None, None, None
    cleaned_url, token = split_anaconda_token(url)
    url_parts = urlparse(cleaned_url)
    remainder_url = Url(host=url_parts.host, port=url_parts.port, path=url_parts.path,
                        query=url_parts.query).url
    return remainder_url, url_parts.scheme, url_parts.auth, token


def disable_ssl_verify_warning():
    """Disables insecure request warnings"""
    warnings.simplefilter("ignore", InsecureRequestWarning)


def preload_openssl():
    """Because our openssl library lives in Librar/bin, and because that may not be on PATH
    if conda.exe in Scripts is called directly, try this preload to avoid user issues."""
    libbin_path = os.path.join(sys.prefix, "Library", "bin")
    libssl_dllname = "libssl"
    libcrypto_dllname = "libcrypto"
    libssl_version = "-1_1"
    libssl_arch = ""
    if sys.maxsize > 2 ** 32:
        libssl_arch = "-x64"
    so_name = libssl_dllname + libssl_version + libssl_arch
    libssl_path2 = os.path.join(libbin_path, so_name)
    # if version 1.1 is not found, try to load 1.0
    if not os.path.exists(libssl_path2 + ".dll"):
        libssl_version = ""
        libssl_arch = ""
        libssl_dllname = "ssleay32"
        libcrypto_dllname = "libeay32"
        so_name = libssl_dllname
        libssl_path2 = os.path.join(libbin_path, so_name)
    libssl_path = find_library(so_name)
    if not libssl_path:
        libssl_path = libssl_path2
    # crypto library might exists ...
    so_name = libcrypto_dllname + libssl_version + libssl_arch
    libcrypto_path = find_library(so_name)
    if not libcrypto_path:
        libcrypto_path = os.path.join(sys.prefix, "Library", "bin", so_name)
    kernel32 = ctypes.windll.kernel32
    h_mod = kernel32.GetModuleHandleA(libcrypto_path)
    if not h_mod:
        ctypes.WinDLL(libcrypto_path)
    h_mod = kernel32.GetModuleHandleA(libssl_path)
    if not h_mod:
        ctypes.WinDLL(libssl_path)


def download(
    url,
    target_full_path,
    md5=None,
    sha256=None,
    size=None,
    progress_update_callback=None,
    ssl_verify=True,
    remote_connect_timeout_secs=9.15,
    remote_read_timeout_secs=60.0,
    proxies=None,
):
    if os.path.exists(target_full_path):
        raise IOError(f"Target {target_full_path} for {url} already exists")
    if sys.platform == "win32":
        preload_openssl()
    if not ssl_verify:
        disable_ssl_verify_warning()

    try:
        timeout = remote_connect_timeout_secs, remote_read_timeout_secs
        resp = requests.get(url, stream=True, proxies=proxies, timeout=timeout)
        if LOGGER.isEnabledFor(logging.DEBUG):
            LOGGER.debug(str(resp)[:256])
        resp.raise_for_status()

        content_length = int(resp.headers.get("Content-Length", 0))

        # prefer sha256 over md5 when both are available
        checksum_builder = checksum_type = checksum = None
        if sha256:
            checksum_builder = hashlib.new("sha256")
            checksum_type = "sha256"
            checksum = sha256
        elif md5:
            checksum_builder = hashlib.new("md5") if md5 else None
            checksum_type = "md5"
            checksum = md5

        size_builder = 0
        try:
            with open(target_full_path, "wb") as fh:
                streamed_bytes = 0
                for chunk in resp.iter_content(2 ** 14):
                    # chunk could be the decompressed form of the real data
                    # but we want the exact number of bytes read till now
                    streamed_bytes = resp.raw.tell()
                    try:
                        fh.write(chunk)
                    except IOError as e:
                        message = (
                            "Failed to write to %(target_path)s\n  errno: %(errno)d"
                        )
                        # TODO: make this CondaIOError
                        raise CondaError(
                            message, target_path=target_full_path, errno=e.errno
                        )

                    checksum_builder and checksum_builder.update(chunk)
                    size_builder += len(chunk)

                    if content_length and 0 <= streamed_bytes <= content_length:
                        if progress_update_callback:
                            progress_update_callback(streamed_bytes / content_length)

            if content_length and streamed_bytes != content_length:
                # TODO: needs to be a more-specific error type
                message = (
                    "Downloaded bytes did not match Content-Length\n"
                    f"  url: {url}\n"
                    f"  target_path: {target_path}\n"
                    f"  Content-Length: {content_length}\n"
                    f"  downloaded bytes: {downloaded_bytes}\n"
                )
                raise RuntimeError(
                    message,
                    url=url,
                    target_path=target_full_path,
                    content_length=content_length,
                    downloaded_bytes=streamed_bytes,
                )

        except (IOError, OSError) as e:
            if e.errno == 104:
                # Connection reset by peer
                LOGGER.debug("%s, trying again" % e)
            raise

        if checksum:
            actual_checksum = checksum_builder.hexdigest()
            if actual_checksum != checksum:
                LOGGER.debug(
                    "%s mismatch for download: %s (%s != %s)",
                    checksum_type,
                    url,
                    actual_checksum,
                    checksum,
                )
                raise RuntimeError(
                    url, target_full_path, checksum_type, checksum, actual_checksum
                )
        if size is not None:
            actual_size = size_builder
            if actual_size != size:
                LOGGER.debug(
                    "size mismatch for download: %s (%s != %s)", url, actual_size, size
                )
                raise RuntimeError(url, target_full_path, "size", size, actual_size)

    except RequestsProxyError:
        raise

    except InvalidSchema as e:
        if "SOCKS" in str(e):
            message = (
                "Requests has identified that your current working environment is configured "
                "to use a SOCKS proxy, but pysocks is not installed.  To proceed, remove your "
                "proxy configuration, run 'conda install pysocks', and then you can re-enable "
                "your proxy configuration."
            )
            raise RuntimeError(message)
        else:
            raise

    except (ConnectionError, HTTPError, SSLError) as e:
        help_message = (
            "An HTTP error occurred when trying to retrieve this URL. "
            "HTTP errors are often intermittent, and a simple retry will get you on your way."
        )
        raise RuntimeError(
            help_message,
            url,
            getattr(e.response, "status_code", None),
            getattr(e.response, "reason", None),
            getattr(e.response, "elapsed", None),
            e.response,
            caused_by=e,
        )


def download_text(
    url,
    ssl_verify=True,
    remote_connect_timeout_secs=9.15,
    remote_read_timeout_secs=60.0,
    proxies=None,
):
    if sys.platform == "win32":
        preload_openssl()
    if not ssl_verify:
        disable_ssl_verify_warning()
    try:
        timeout = remote_connect_timeout_secs, remote_read_timeout_secs
        response = requests.get(
            url, stream=True, proxies=proxies, timeout=timeout
        )
        if LOGGER.isEnabledFor(logging.DEBUG):
            LOGGER.debug(str(response)[:256])
        response.raise_for_status()
    except RequestsProxyError:
        raise
    except InvalidSchema as e:
        if "SOCKS" in str(e):
            message = (
                "Requests has identified that your current working environment is configured "
                "to use a SOCKS proxy, but pysocks is not installed.  To proceed, remove your "
                "proxy configuration, run `conda install pysocks`, and then you can re-enable "
                "your proxy configuration."
            )
            raise RuntimeError(message)
        else:
            raise
    except (ConnectionError, HTTPError, SSLError) as e:
        status_code = getattr(e.response, "status_code", None)
        if status_code == 404:
            help_message = (
                "An HTTP error occurred when trying to retrieve this URL. "
                "The URL does not exist."
            )
        else:
            help_message = (
                "An HTTP error occurred when trying to retrieve this URL. "
                "HTTP errors are often intermittent, and a simple retry will get you on your way."
            )
        raise RuntimeError(
            help_message,
            url,
            status_code,
            getattr(e.response, "reason", None),
            getattr(e.response, "elapsed", None),
            e.response,
            caused_by=e,
        )
    return response.text


class TmpDownload(object):
    """
    Context manager to handle downloads to a tempfile
    """

    def __init__(self, url, verbose=True):
        self.url = url
        self.verbose = verbose

    def __enter__(self):
        if "://" not in self.url:
            # if we provide the file itself, no tmp dir is created
            self.tmp_dir = None
            return self.url
        else:
            self.tmp_dir = tempfile.mkdtemp()
            dst = os.path.join(self.tmp_dir, os.path.basename(self.url))
            download(self.url, dst)
            return dst

    def __exit__(self, exc_type, exc_value, traceback):
        if self.tmp_dir:
            shutil.rmtree(self.tmp_dir)
