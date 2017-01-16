# (c) Continuum Analytics, Inc. / http://continuum.io
# All Rights Reserved
#
# conda is distributed under the terms of the BSD 3-clause license.
# Consult LICENSE.txt or http://opensource.org/licenses/BSD-3-Clause.

from __future__ import absolute_import, division, print_function

import logging
import sys

from conda_build.conda_interface import ArgumentParser, add_parser_channels

from conda_build import __version__
from conda_build.render import render_recipe, set_language_env_vars, bldpkg_path, output_yaml
from conda_build.completers import (RecipeCompleter, PythonVersionCompleter, RVersionsCompleter,
                                    LuaVersionsCompleter, NumPyVersionCompleter)
from conda_build.config import Config
from conda_build.utils import LoggingContext

on_win = (sys.platform == 'win32')


def get_render_parser():
    p = ArgumentParser(
        description="""
Tool for building conda packages. A conda package is a binary tarball
containing system-level libraries, Python modules, executable programs, or
other components. conda keeps track of dependencies between packages and
platform specifics, making it simple to create working environments from
        different sets of packages.""",
        conflict_handler='resolve'
    )
    p.add_argument(
        '-V', '--version',
        action='version',
        help='Show the conda-build version number and exit.',
        version='conda-build %s' % __version__,
    )
    p.add_argument(
        '-n', "--no-source",
        action="store_true",
        help="When templating can't be completed, do not obtain the \
source to try fill in related template variables.",
    )
    p.add_argument(
        "--output",
        action="store_true",
        help="Output the conda package filename which would have been "
               "created",
    )
    p.add_argument(
        '--python',
        action="append",
        help="Set the Python version used by conda build.",
        metavar="PYTHON_VER",
        choices=PythonVersionCompleter(),
    )
    p.add_argument(
        '--perl',
        action="append",
        help="Set the Perl version used by conda build.",
        metavar="PERL_VER",
    )
    p.add_argument(
        '--numpy',
        action="append",
        help="Set the NumPy version used by conda build.",
        metavar="NUMPY_VER",
        choices=NumPyVersionCompleter(),
    )
    p.add_argument(
        '--R',
        action="append",
        help="""Set the R version used by conda build.""",
        metavar="R_VER",
        choices=RVersionsCompleter(),
    )
    p.add_argument(
        '--lua',
        action="append",
        help="Set the Lua version used by conda build.",
        metavar="LUA_VER",
        choices=LuaVersionsCompleter(),
    )
    p.add_argument(
        '--bootstrap',
        help="""Provide initial configuration in addition to recipe.
        Can be a path to or name of an environment, which will be emulated
        in the package.""",
    )
    p.add_argument(
        '--append-file',
        help="""Append data in meta.yaml with fields from this file.  Jinja2 is not done
        on appended fields""",
        dest='append_sections_file',
    )
    p.add_argument(
        '--clobber-file',
        help="""Clobber data in meta.yaml with fields from this file.  Jinja2 is not done
        on clobbered fields.""",
        dest='clobber_sections_file',
    )
    p.add_argument(
        '-m', '--variant-config-files',
        dest='variant_config_files',
        action="append",
        help="""Additional variant config files to add.  These yaml files can contain
        keys such as `c_compiler` and `target_platform` to form a build matrix."""
    )

    add_parser_channels(p)
    return p


def parse_args(args):
    p = get_render_parser()
    p.add_argument(
        '-f', '--file',
        help="write YAML to file, given as argument here.\
              Overwrites existing files."
    )
    # we do this one separately because we only allow one entry to conda render
    p.add_argument(
        'recipe',
        metavar='RECIPE_PATH',
        choices=RecipeCompleter(),
        help="Path to recipe directory.",
    )
    # this is here because we have a different default than build
    p.add_argument(
        '--verbose',
        action='store_true',
        help='Enable verbose output from download tools and progress updates',
    )
    args = p.parse_args(args)
    return p, args


def execute(args):
    p, args = parse_args(args)

    config = Config()
    set_language_env_vars(args, p, config)

    metadata_tuples = render_recipe(args.recipe, config=config, no_download_source=args.no_source)
    if args.output:
        with LoggingContext(logging.CRITICAL + 1):
            for (metadata, _, _) in metadata_tuples:
                print(bldpkg_path(metadata))
    else:
        logging.basicConfig(level=logging.INFO)
        for (metadata, _, _) in metadata_tuples:
            print(output_yaml(metadata, args.file))


def main():
    return execute(sys.argv[1:])


if __name__ == '__main__':
    main()
