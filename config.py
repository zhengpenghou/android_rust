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

import argparse
import os
import subprocess
import stat
from string import Template

import build_platform
from paths import *


HOST_TARGETS: list[str] = [build_platform.triple()] + build_platform.alt_triples()
DEVICE_TARGETS: list[str] = ['aarch64-linux-android', 'armv7-linux-androideabi',
                  'x86_64-linux-android', 'i686-linux-android', 'riscv64-linux-android']

ALL_TARGETS: list[str] = HOST_TARGETS + DEVICE_TARGETS

LTO_DENYLIST_TARGETS: list[str] = ['armv7-linux-androideabi']

ANDROID_TARGET_VERSION: str = '31'

CONFIG_TOML_TEMPLATE:           Path = TEMPLATES_PATH / 'config.toml.template'
DEVICE_CC_WRAPPER_TEMPLATE:     Path = TEMPLATES_PATH / 'device_cc_wrapper.template'
DEVICE_LINKER_WRAPPER_TEMPLATE: Path = TEMPLATES_PATH / 'device_linker_wrapper.template'
DEVICE_TARGET_TEMPLATE:         Path = TEMPLATES_PATH / 'device_target.template'
HOST_CC_WRAPPER_TEMPLATE:       Path = TEMPLATES_PATH / 'host_cc_wrapper.template'
HOST_CXX_WRAPPER_TEMPLATE:      Path = TEMPLATES_PATH / 'host_cxx_wrapper.template'
HOST_LINKER_WRAPPER_TEMPLATE:   Path = TEMPLATES_PATH / 'host_linker_wrapper.template'
HOST_TARGET_TEMPLATE:           Path = TEMPLATES_PATH / 'host_target.template'

LINKER_PIC_FLAG:     str = '-Wl,-mllvm,-relocation-model=pic'
MACOSX_VERSION_FLAG: str = '-mmacosx-version-min=10.14'


def instantiate_template_exec(template_path: Path, output_path: Path, **kwargs):
    instantiate_template_file(template_path, output_path, make_exec=True, **kwargs)

def instantiate_template_file(template_path: Path, output_path: Path, make_exec: bool = False, **kwargs) -> None:
    with open(template_path) as template_file:
        template = Template(template_file.read())
        with open(output_path, 'w') as output_file:
            output_file.write(template.substitute(**kwargs))
    if make_exec:
        output_path.chmod(output_path.stat().st_mode | stat.S_IEXEC)


def host_config(target: str, macosx_flags: str, linker_flags: str) -> str:
    cc_wrapper_name     = OUT_PATH_WRAPPERS / ('clang-%s' % target)
    cxx_wrapper_name    = OUT_PATH_WRAPPERS / ('clang++-%s' % target)
    linker_wrapper_name = OUT_PATH_WRAPPERS / ('linker-%s' % target)

    instantiate_template_exec(
        HOST_CC_WRAPPER_TEMPLATE,
        cc_wrapper_name,
        real_cc=CC_PATH,
        target=target,
        macosx_flags=macosx_flags)

    instantiate_template_exec(
        HOST_CXX_WRAPPER_TEMPLATE,
        cxx_wrapper_name,
        real_cxx=CXX_PATH,
        target=target,
        macosx_flags=macosx_flags,
        cxxstd=CXXSTD_PATH)

    instantiate_template_exec(
        HOST_LINKER_WRAPPER_TEMPLATE,
        linker_wrapper_name,
        real_cxx=CXX_PATH,
        target=target,
        macosx_flags=macosx_flags,
        linker_flags=linker_flags)

    with open(HOST_TARGET_TEMPLATE, 'r') as template_file:
        return Template(template_file.read()).substitute(
            target=target,
            cc=cc_wrapper_name,
            cxx=cxx_wrapper_name,
            linker=linker_wrapper_name,
            ar=AR_PATH,
            ranlib=RANLIB_PATH)


def device_config(target: str, lto_flag: str, linker_flags: str) -> str:
    cc_wrapper_name     = OUT_PATH_WRAPPERS / ('clang-%s' % target)
    linker_wrapper_name = OUT_PATH_WRAPPERS / ('linker-%s' % target)

    clang_target = target + ANDROID_TARGET_VERSION

    if target in LTO_DENYLIST_TARGETS:
        lto_flag = ''

    instantiate_template_exec(
        DEVICE_CC_WRAPPER_TEMPLATE,
        cc_wrapper_name,
        real_cc=CC_PATH,
        target=clang_target,
        sysroot=NDK_SYSROOT_PATH,
        lto_flag=lto_flag)

    instantiate_template_exec(
        DEVICE_LINKER_WRAPPER_TEMPLATE,
        linker_wrapper_name,
        real_cc=CC_PATH,
        target=clang_target,
        sysroot=NDK_SYSROOT_PATH,
        linker_flags=linker_flags,
        lto_flag=lto_flag)

    with open(DEVICE_TARGET_TEMPLATE, 'r') as template_file:
        return Template(template_file.read()).substitute(
            target=target,
            cc=cc_wrapper_name,
            linker=linker_wrapper_name,
            ar=AR_PATH)


def configure(args: argparse.ArgumentParser, env: dict[str, str]):
    """Generates config.toml and compiler wrapers for the rustc build."""

    #
    # Compute compiler/linker flags
    #

    macosx_flags:          str = ''
    host_ld_selector:      str = '-fuse-ld=lld' if build_platform.is_linux() else ''
    host_bin_search:       str = ('-B' + GCC_TOOLCHAIN_PATH.as_posix()) if build_platform.is_linux() else ''
    host_llvm_libpath:     str = '-L' + LLVM_CXX_RUNTIME_PATH.as_posix()
    host_rpath_buildtime:  str = '-Wl,-rpath,' + LLVM_CXX_RUNTIME_PATH.as_posix()
    host_rpath_runtime:    str = '-Wl,-rpath,' + (
        '$ORIGIN/../lib64' if build_platform.is_linux() else '@loader_path/../lib64')

    lto_flag: str = ''
    if args.lto == 'full':
        lto_flag = '-flto=full'
    elif args.lto == 'thin':
        lto_flag = '-flto=thin'

    if build_platform.is_darwin():
        # Apple removed the normal sysroot at / on Mojave+, so we need
        # to go hunt for it on OSX
        # On pre-Mojave, this command will output the empty string.
        output = subprocess.check_output(
            ['xcrun', '--sdk', 'macosx', '--show-sdk-path'])
        macosx_flags = (
            MACOSX_VERSION_FLAG +
            " --sysroot " + output.rstrip().decode('utf-8'))

    host_linker_flags = ' '.join([
        host_ld_selector,
        LINKER_PIC_FLAG,
        lto_flag,
        host_bin_search,
        host_llvm_libpath,
        host_rpath_buildtime,
        host_rpath_runtime])

    device_linker_flags = LINKER_PIC_FLAG

    #
    # Update environment variables
    #

    env['PATH'] = os.pathsep.join(
        [p.as_posix() for p in [
          RUST_PREBUILT_PATH / 'bin',
          CMAKE_PREBUILT_PATH / 'bin',
          NINJA_PREBUILT_PATH,
          BUILD_TOOLS_PREBUILT_PATH,
        ]] + [env['PATH']])

    # Only adjust the library path on Linux - on OSX, use the devtools curl
    if build_platform.is_linux():
        if 'LIBRARY_PATH' in env:
            old_library_path = ':{0}'.format(env['LIBRARY_PATH'])
        else:
            old_library_path = ''
        env['LIBRARY_PATH'] = '{0}{1}'.format(CURL_PREBUILT_PATH / 'lib', old_library_path)

    # Tell the rust bootstrap system where to place its final products
    env['DESTDIR'] = OUT_PATH_PACKAGE

    # Pass additional flags to the Rust compiler
    env['RUSTFLAGS'] = '-C relocation-model=pic'

    if args.lto != 'none':
        env['RUSTFLAGS'] += ' -C linker-plugin-lto'

    # The LTO flag must be passed via the HOST_CFLAGS environment variable due
    # to the fact that including it in the host c/cxx wrappers will cause the
    # CMake compiler detection routine to fail during LLVM configuration.
    #
    # The Rust bootstrap system will include the value of HOST_CFLAGS in all
    # invocations of either the C or C++ compiler for host targets.  Some
    # device targets do not currently support LTO and as such the LTO flag is
    # passed to supported device targets via the compiler wrappers, which is
    # why HOST_CFLAGS is used instead of CFLAGS.  The LLVM build system will
    # receive the LTO flag value from the llvm::cflags and llvm::cxxflags
    # values in the config.toml file instantiated below.
    #
    # Because Rust's bootstrap system doesn't pass the linker wrapper into the
    # LLVM build system AND doesn't respect the LDFLAGS environment variable
    # this value gets into the LLVM build system via the llvm::ldflags value in
    # config.toml and the Rust build system via the host linker wrapper, both
    # of which are instantiated below using the same value for host_linker_flags.
    #
    # Note: Rust's bootstrap system will use CFLAGS for both C and C++ compiler
    #       invocations.
    #
    # Note: LTO is not enabled for device targets due to a bug either in the
    #       ARMv7 implementation of compiler-rt or in LLD, which prevents the
    #       resulting LTOed artifacts from linking properly.  See b/201551165.
    #
    # Note: The Rust bootstrap system will copy HOST_CFLAGS into CFLAGS when
    #       invoking the LLVM build system.  As a result the LTO argument will
    #       appear twice in the CMake language flag variables.
    env['HOST_CFLAGS'] = lto_flag

    #
    # Intantiate wrappers
    #

    host_configs = '\n'.join(
        [host_config(target, macosx_flags, host_linker_flags) for target in HOST_TARGETS])
    device_configs = '\n'.join(
        [device_config(target, lto_flag, device_linker_flags) for target in DEVICE_TARGETS])

    all_targets = '[' + ','.join(
        ['"' + target + '"' for target in ALL_TARGETS]) + ']'

    instantiate_template_file(
        CONFIG_TOML_TEMPLATE,
        OUT_PATH_RUST_SOURCE / 'config.toml',
        llvm_cflags=lto_flag,
        llvm_cxxflags=lto_flag,
        llvm_ldflags=host_linker_flags,
        all_targets=all_targets,
        cargo=CARGO_PATH,
        rustc=RUSTC_PATH,
        python=PYTHON_PATH,
        host_configs=host_configs,
        device_configs=device_configs)
