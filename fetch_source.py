#!/usr/bin/env python3
# Copyright (C) 2021 The Android Open Source Project
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


import argparse
import re
import subprocess
import sys

from paths import RUST_SOURCE_PATH


COMMAND_GIT_ADD    : str = "git add ."
COMMAND_GIT_COMMIT : str = "git commit --no-verify -m 'Importing rustc-%s'"
COMMAND_GIT_RM     : str = "git rm -fr *"
COMMAND_FETCH      : str = "curl %s | tar xz --strip-components=1"
COMMAND_REPO       : str = "repo start rust-update-source-%s"

RUSTC_SOURCE_URL_VERSION_TEMPLATE : str = "https://static.rust-lang.org/dist/rustc-%s-src.tar.gz"
RUSTC_SOURCE_URL_BETA : str = "https://static.rust-lang.org/dist/rustc-beta-src.tar.gz"

VERSION_PATTERN : re.Pattern = re.compile("\d+\.\d+\.\d+")


def exec_rustc_src_command(command, error_string, stdout=subprocess.DEVNULL) -> None:
  result = subprocess.run(command, shell=True, cwd=RUST_SOURCE_PATH, stdout=stdout)
  if result.returncode != 0:
    print("{}:\n{}".format(error_string, result.stderr))
    exit(-2)


def construct_archive_url(rust_version, beta) -> str:
  if beta:
    return RUSTC_SOURCE_URL_BETA
  else:
    return RUSTC_SOURCE_URL_VERSION_TEMPLATE % rust_version


def version_string_type(arg_string : str) -> str:
  if VERSION_PATTERN.match(arg_string):
    return arg_string
  else:
    raise argparse.ArgumentTypeError


def parse_args() -> argparse.ArgumentParser:
  parser = argparse.ArgumentParser(description='Fetch and unpack a Rust source archive')

  parser.add_argument("-b", "--beta", dest="beta", action="store_true", default=False,
    help="fetch the beta archive")
  parser.add_argument("rust_version", action="store", type=version_string_type)

  return parser.parse_args()


def main() -> None:
  args = parse_args()

  print("\nCreating branch")
  command_repo = COMMAND_REPO % (args.rust_version + ("-beta" if args.beta else ""))
  exec_rustc_src_command(command_repo, "Error creating repo for source update")

  print("Deleting old files")
  exec_rustc_src_command(COMMAND_GIT_RM, "Error deleting old files from git")

  archive_url = construct_archive_url(args.rust_version, args.beta)
  print("Fetching archive %s\n" % archive_url)
  exec_rustc_src_command(
    COMMAND_FETCH % archive_url,
    "Error fetching source for Rust version %s" % args.rust_version,
    stdout=None)

  print("\nCommiting new files")
  exec_rustc_src_command(COMMAND_GIT_ADD, "Error adding new files to git")
  exec_rustc_src_command(COMMAND_GIT_COMMIT % args.rust_version, "Error commiting new files to git")


if __name__ == '__main__':
  main()