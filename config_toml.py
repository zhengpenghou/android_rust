# Copyright (C) 2019 The Android Open Source Project
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Handles generation of config.toml for the rustc build."""

import os
import subprocess
import stat

import build_platform
from paths import *

host_targets = [build_platform.triple()] + build_platform.alt_triples()
device_targets = ['aarch64-linux-android', 'armv7-linux-androideabi',
                  'x86_64-linux-android', 'i686-linux-android']
all_targets = host_targets + device_targets


def configure(rustc_path):
    """Generates config.toml for the rustc build."""
    with (rustc_path / 'config.toml').open('w') as config_toml:
        cargo  = RUST_PREBUILT_PATH / 'bin' / 'cargo'
        rustc  = RUST_PREBUILT_PATH / 'bin' / 'rustc'
        cc     = LLVM_PREBUILT_PATH / 'bin' / 'clang'
        cxx    = LLVM_PREBUILT_PATH / 'bin' / 'clang++'
        ar     = LLVM_PREBUILT_PATH / 'bin' / 'llvm-ar'
        ranlib = LLVM_PREBUILT_PATH / 'bin' / 'llvm-ranlib'
        cxxstd = LLVM_PREBUILT_PATH / 'include' / 'c++' / 'v1'

        # Add the path at which libc++ can be found in Android checkouts
        cxx_linker_flags = ' -Wl,-rpath,'
        if build_platform.system() == 'darwin':
            cxx_linker_flags += '@loader_path/../lib64'
        else:
            cxx_linker_flags += '\\$ORIGIN/../lib64'
        # Add the path at which libc++ can be found during the build
        cxx_linker_flags += ' -Wl,-rpath,' + LLVM_CXX_RUNTIME_PATH.as_posix()

        def host_config(target):
            wrapper_name = TOOLCHAIN_PATH / ('clang-%s' % target)
            cxx_wrapper_name = TOOLCHAIN_PATH / ('clang++-%s' % target)

            sysroot = None
            # Apple removed the normal sysroot at / on Mojave+, so we need
            # to go hunt for it on OSX
            # On pre-Mojave, this command will output the empty string.
            if build_platform.system() == 'darwin':
                output = subprocess.check_output(['xcrun', '--sdk', 'macosx',
                                                  '--show-sdk-path'])
                sysroot = output.rstrip().decode('utf-8')

            if sysroot:
                sysroot_flags = "--sysroot " + sysroot
            else:
                sysroot_flags = ""

            ld_option = None
            if build_platform.system() == 'linux':
                ld_option = '-fuse-ld=lld -Wno-unused-command-line-argument'
            else:
                ld_option = ''

            with open(wrapper_name, 'w') as f:
                f.write("""\
#!/bin/sh
{real_cc} $* {ld_option} --target={target} {sysroot_flags}
""".format(real_cc=cc, ld_option=ld_option, target=target, sysroot_flags=sysroot_flags))

            with open(cxx_wrapper_name, 'w') as f:
                f.write("""\
#!/bin/sh
{real_cxx} -I{cxxstd} $* {ld_option} --target={target} {sysroot_flags} {cxx_linker_flags} \
        -stdlib=libc++
""".format(real_cxx=cxx, ld_option=ld_option, target=target, sysroot_flags=sysroot_flags,
           cxxstd=cxxstd,
           cxx_linker_flags=cxx_linker_flags))

            s = os.stat(wrapper_name)
            os.chmod(wrapper_name, s.st_mode | stat.S_IEXEC)
            s = os.stat(cxx_wrapper_name)
            os.chmod(cxx_wrapper_name, s.st_mode | stat.S_IEXEC)
            return """\
[target.{target}]
cc = "{cc}"
cxx = "{cxx}"
ar = "{ar}"
ranlib = "{ranlib}"
linker = "{cxx}"
""".format(cc=wrapper_name, cxx=cxx_wrapper_name, ar=ar, ranlib=ranlib, target=target)

        def device_config(target):
            wrapper_name = TOOLCHAIN_PATH / ('clang-%s' % target)
            with open(wrapper_name, 'w') as f:
                f.write("""\
#!/bin/sh
{real_cc} $* -fuse-ld=lld -Wno-unused-command-line-argument --target={target} \
        --sysroot={sysroot} -L{gcc_libdir} -L{sys_dir} -isystem {ndk_includes} \
        -isystem {target_includes}
""".format(real_cc=cc,
           sysroot=plat_ndk_sysroot_path(target),
           ndk_includes=NDK_INCLUDE_PATH,
           target_includes=target_includes_path(target),
           target=target,
           gcc_libdir=gcc_libdir_path(target),
           sys_dir=plat_ndk_llvm_libs_path(target)))

            s = os.stat(wrapper_name)
            os.chmod(wrapper_name, s.st_mode | stat.S_IEXEC)
            return """\
[target.{target}]
cc="{cc}"
ar="{ar}"
""".format(ar=ar, cc=wrapper_name, target=target)

        host_configs = '\n'.join(
            [host_config(target) for target in host_targets])
        device_configs = '\n'.join(
            [device_config(target) for target in device_targets])

        all_targets_config = '[' + ','.join(
            ['"' + target + '"' for target in all_targets]) + ']'
        config_toml.write("""\
changelog-seen = 2
[llvm]
ninja = true
targets = "AArch64;ARM;X86"
experimental-targets = ""
use-libcxx = true
[build]
target = {all_targets_config}
cargo = "{cargo}"
rustc = "{rustc}"
verbose = 1
profiler = true
docs = false
submodules = false
locked-deps = true
vendor = true
full-bootstrap = true
extended = true
tools = ["cargo", "clippy", "rustfmt", "rust-analyzer"]
cargo-native-static = true
[install]
prefix = "/"
sysconfdir = "etc"
[rust]
channel = "dev"
remap-debuginfo = true
deny-warnings = false
{host_configs}
{device_configs}
""".format(cargo=cargo,
           rustc=rustc,
           cc=cc,
           cxx=cxx,
           ar=ar,
           ranlib=ranlib,
           host_configs=host_configs,
           device_configs=device_configs,
           all_targets_config=all_targets_config))
