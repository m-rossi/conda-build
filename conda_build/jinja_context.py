from __future__ import absolute_import, division, print_function

from functools import partial
import json
import logging
import os
import re
import sys

import jinja2

from .conda_interface import PY3
from .environ import get_dict as get_environ
from .metadata import select_lines, ns_cfg
from .utils import get_installed_packages


class UndefinedNeverFail(jinja2.Undefined):
    """
    A class for Undefined jinja variables.
    This is even less strict than the default jinja2.Undefined class,
    because it permits things like {{ MY_UNDEFINED_VAR[:2] }} and
    {{ MY_UNDEFINED_VAR|int }}. This can mask lots of errors in jinja templates, so it
    should only be used for a first-pass parse, when you plan on running a 'strict'
    second pass later.
    """
    all_undefined_names = []

    def __init__(self, hint=None, obj=jinja2.runtime.missing, name=None,
                 exc=jinja2.exceptions.UndefinedError):
        UndefinedNeverFail.all_undefined_names.append(name)
        jinja2.Undefined.__init__(self, hint, obj, name, exc)

    __add__ = __radd__ = __mul__ = __rmul__ = __div__ = __rdiv__ = \
    __truediv__ = __rtruediv__ = __floordiv__ = __rfloordiv__ = \
    __mod__ = __rmod__ = __pos__ = __neg__ = __call__ = \
    __getitem__ = __lt__ = __le__ = __gt__ = __ge__ = \
    __complex__ = __pow__ = __rpow__ = \
        lambda self, *args, **kwargs: UndefinedNeverFail(hint=self._undefined_hint,
                                                         obj=self._undefined_obj,
                                                         name=self._undefined_name,
                                                         exc=self._undefined_exception)

    __str__ = __repr__ = \
        lambda *args, **kwargs: u''

    __int__ = lambda _: 0
    __float__ = lambda _: 0.0

    def __getattr__(self, k):
        try:
            return object.__getattr__(self, k)
        except AttributeError:
            return UndefinedNeverFail(hint=self._undefined_hint,
                                      obj=self._undefined_obj,
                                      name=self._undefined_name + '.' + k,
                                      exc=self._undefined_exception)


class FilteredLoader(jinja2.BaseLoader):
    """
    A pass-through for the given loader, except that the loaded source is
    filtered according to any metadata selectors in the source text.
    """

    def __init__(self, unfiltered_loader, config):
        self._unfiltered_loader = unfiltered_loader
        self.list_templates = unfiltered_loader.list_templates
        self.config = config

    def get_source(self, environment, template):
        contents, filename, uptodate = self._unfiltered_loader.get_source(environment,
                                                                          template)
        return select_lines(contents, ns_cfg(self.config)), filename, uptodate


def load_setup_py_data(config, setup_file='setup.py', from_recipe_dir=False, recipe_dir=None,
                       permit_undefined_jinja=True):
    _setuptools_data = {}
    log = logging.getLogger(__name__)

    def setup(**kw):
        _setuptools_data.update(kw)

    import setuptools
    import distutils.core

    cd_to_work = False
    path_backup = sys.path

    if from_recipe_dir and recipe_dir:
        setup_file = os.path.abspath(os.path.join(recipe_dir, setup_file))
    elif os.path.exists(config.work_dir):
        cd_to_work = True
        cwd = os.getcwd()
        os.chdir(config.work_dir)
        if not os.path.isabs(setup_file):
            setup_file = os.path.join(config.work_dir, setup_file)
        # this is very important - or else if versioneer or otherwise is in the start folder,
        # things will pick up the wrong versioneer/whatever!
        sys.path.insert(0, config.work_dir)
    else:
        message = ("Did not find setup.py file in manually specified location, and source "
                  "not downloaded yet.")
        if permit_undefined_jinja:
            log.debug(message)
            return {}
        else:
            raise RuntimeError(message)

    # Patch setuptools, distutils
    setuptools_setup = setuptools.setup
    distutils_setup = distutils.core.setup
    numpy_setup = None

    versioneer = None
    if 'versioneer' in sys.modules:
        versioneer = sys.modules['versioneer']
        del sys.modules['versioneer']

    try:
        import numpy.distutils.core
        numpy_setup = numpy.distutils.core.setup
        numpy.distutils.core.setup = setup
    except ImportError:
        log.debug("Failed to import numpy for setup patch.  Is numpy installed?")

    setuptools.setup = distutils.core.setup = setup
    ns = {
        '__name__': '__main__',
        '__doc__': None,
        '__file__': setup_file,
    }
    if os.path.isfile(setup_file):
        code = compile(open(setup_file).read(), setup_file, 'exec', dont_inherit=1)
        exec(code, ns, ns)
    else:
        if not permit_undefined_jinja:
            raise TypeError('{} is not a file that can be read'.format(setup_file))

    sys.modules['versioneer'] = versioneer

    distutils.core.setup = distutils_setup
    setuptools.setup = setuptools_setup
    if numpy_setup:
        numpy.distutils.core.setup = numpy_setup
    if cd_to_work:
        os.chdir(cwd)
    # remove our workdir from sys.path
    sys.path = path_backup
    return _setuptools_data if _setuptools_data else None


def load_setuptools(config, setup_file='setup.py', from_recipe_dir=False, recipe_dir=None,
                    permit_undefined_jinja=True):
    log = logging.getLogger(__name__)
    log.warn("Deprecation notice: the load_setuptools function has been renamed to "
             "load_setup_py_data.  load_setuptools will be removed in a future release.")
    return load_setup_py_data(config=config, setup_file=setup_file, from_recipe_dir=from_recipe_dir,
                              recipe_dir=recipe_dir, permit_undefined_jinja=permit_undefined_jinja)


def load_npm():
    # json module expects bytes in Python 2 and str in Python 3.
    mode_dict = {'mode': 'r', 'encoding': 'utf-8'} if PY3 else {'mode': 'rb'}
    with open('package.json', **mode_dict) as pkg:
        return json.load(pkg)


def load_file_regex(config, load_file, regex_pattern, from_recipe_dir=False,
                    recipe_dir=None, permit_undefined_jinja=True):
    match = False
    log = logging.getLogger(__name__)

    cd_to_work = False

    if from_recipe_dir and recipe_dir:
        load_file = os.path.abspath(os.path.join(recipe_dir, load_file))
    elif os.path.exists(config.work_dir):
        cd_to_work = True
        cwd = os.getcwd()
        os.chdir(config.work_dir)
        if not os.path.isabs(load_file):
            load_file = os.path.join(config.work_dir, load_file)
    else:
        message = ("Did not find {} file in manually specified location, and source "
                  "not downloaded yet.".format(load_file))
        if permit_undefined_jinja:
            log.debug(message)
            return {}
        else:
            raise RuntimeError(message)

    if os.path.isfile(load_file):
        match = re.search(regex_pattern, open(load_file, 'r').read())
    else:
        if not permit_undefined_jinja:
            raise TypeError('{} is not a file that can be read'.format(load_file))

    # Reset the working directory
    if cd_to_work:
        os.chdir(cwd)

    return match if match else None


def pin_compatible(config, package_name, package_table=None, permit_undefined_jinja=True):
    """Query a compatibility database, or just guess about compatibility based on semantic
    versioning.  Returns string with guess about compatible pinning."""
    log = logging.getLogger(__name__)
    packages = get_installed_packages(config.build_prefix)
    compatibility = None
    if packages.get(package_name):
        version = packages[package_name]['version']
        if package_table and package_name in package_table:
            # Look up compatibilty in table - TODO: need to factor version into this somehow
            compatibility = package_table[package_name]
        else:
            try:
                log.info('Package %s does not have compatibilty entry.  Assuming semantic '
                            'versioning style, and allowing bug-fix revisions.  '
                            'Please add package to lookup table if necessary.', package_name)
                versions = version.split('.')
                compatibility = ">=" + version + "," + ".".join([versions[0], versions[1], '*'])
            except IndexError:
                raise RuntimeError('Package {} does not follow semantic versioning style.  '
                                   'Please add package to lookup table for compatible '
                                   'pinning.'.format(package_name))

    if not compatibility and not permit_undefined_jinja:
        raise RuntimeError("Could not get compatibility information for {} package.  Is the "
                            "build environment created?".format(package_name))
    return compatibility


# map python version to default compiler on windows, to match upstream python
#    This mapping only sets the "native" compiler, and can be overridden by specifying a compiler
#    in the conda-build variant configuration
compilers = {
    'win': {
        'c': {
            '2.7': 'vs2008',
            '3.3': 'vs2010',
            '3.4': 'vs2010',
            '3.5': 'vs2015',
        },
        'cxx': {
            '2.7': 'vs2008',
            '3.3': 'vs2010',
            '3.4': 'vs2010',
            '3.5': 'vs2015',
        },
        'fortran': 'gfortran',
    },
    'linux': {
        'c': 'gcc',
        'cxx': 'g++',
        'fortran': 'gfortran',
    },
    # TODO: Clang?  System clang, or compiled package?  Can handle either as package.
    'osx': {
        'c': 'gcc',
        'cxx': 'g++',
        'fortran': 'gfortran',
    },
}

runtimes = {
    'vs2008': 'vs2008_runtime',
    'vs2010': 'vs2010_runtime',
    'vs2015': 'vs2015_runtime',
    'gfortran': 'libgfortran',
    'g++': 'libstdc++',
    'gcc': 'libgcc',
}


def _native_compiler(language, config, variant):
    compiler = compilers[config.platform][language]
    if hasattr(compiler, 'keys'):
        compiler = compiler.get(variant.get('python', 'nope'), 'vs2015')
    return compiler


def compiler(language, config, variant, permit_undefined_jinja=False):
    """Support configuration of compilers.  This is somewhat platform specific.

    Native compilers never list their host - it is always implied.  Generally, they are
    metapackages, pointing at a package that does specify the host.  These in turn may be
    metapackages, pointing at a package where the host is the same as the target (both being the
    native architecture).
    """
    native_compiler = _native_compiler(language, config, variant)
    language_compiler_key = '{}_compiler'.format(language)
    # fall back to native if language-compiler is not explicitly set in variant
    compiler = variant.get(language_compiler_key, native_compiler)

    # support cross compilers.  A cross-compiler package will have a name such as
    #    gcc_host_target
    #    gcc_centos5_centos5
    #    gcc_centos7_centos5
    #
    # Note that the host needs to be part of the compiler.  Right now, that means that the compiler
    #    needs to be defined in the variant - not just the native default
    if 'target_platform' in variant:
        if language_compiler_key in variant:
            compiler = '_'.join([variant[language_compiler_key], variant['target_platform']])
        # This is not defined in early stages of parsing.  Let it by if permit_undefined_jinja set
        elif not permit_undefined_jinja:
            raise ValueError("{0} must be set in variant config in order to use target_platform."
                             "  Please set it to the name of the package, including the host "
                             "(e.g. gcc-centos5)".format(language_compiler_key))
    return compiler


def runtime(language, config, variant, permit_undefined_jinja=False):
    """Support configuration of runtimes.  This is somewhat platform specific.

    Native compilers never list their host - it is always implied.  Generally, they are
    metapackages, pointing at a package that does specify the host.  These in turn may be
    metapackages, pointing at a package where the host is the same as the target (both being the
    native architecture).
    """
    native_compiler = _native_compiler(language, config, variant)
    language_compiler_key = '{}_compiler'.format(language)
    # fall back to native if language-compiler is not explicitly set in variant
    compiler = variant.get(language_compiler_key, native_compiler)
    try:
        if 'runtimes' in variant:
            runtime = variant['runtimes'][compiler]
        else:
            runtime = runtimes[compiler]
    except KeyError:
        raise KeyError("Conda-build doesn't know which runtime goes with the {} compiler.  "
                        "Please provide a 'runtimes' section in your variant configuration, "
                        "with the key being your compiler, and the value being the runtime "
                        "package name.".format(compiler))

    if 'target_platform' in variant:
        runtime = '_'.join([runtime, variant['target_platform']])
    return runtime


def context_processor(initial_metadata, recipe_dir, config, permit_undefined_jinja, variant):
    """
    Return a dictionary to use as context for jinja templates.

    initial_metadata: Augment the context with values from this MetaData object.
                      Used to bootstrap metadata contents via multiple parsing passes.
    """
    ctx = get_environ(config=config, m=initial_metadata)
    environ = dict(os.environ)
    environ.update(get_environ(config=config, m=initial_metadata))

    ctx.update(
        load_setup_py_data=partial(load_setup_py_data, config=config, recipe_dir=recipe_dir,
                                   permit_undefined_jinja=permit_undefined_jinja),
        # maintain old alias for backwards compatibility:
        load_setuptools=partial(load_setuptools, config=config, recipe_dir=recipe_dir,
                                permit_undefined_jinja=permit_undefined_jinja),
        load_npm=load_npm,
        load_file_regex=partial(load_file_regex, config=config, recipe_dir=recipe_dir,
                                permit_undefined_jinja=permit_undefined_jinja),
        installed=get_installed_packages(os.path.join(config.build_prefix, 'conda-meta')),
        pin_compatible=partial(pin_compatible, config,
                               permit_undefined_jinja=permit_undefined_jinja),
        compiler=partial(compiler, variant=variant, config=config,
                         permit_undefined_jinja=permit_undefined_jinja),

        runtime=partial(runtime, variant=variant, config=config,
                         permit_undefined_jinja=permit_undefined_jinja),
        variant=variant,
        environ=environ)
    return ctx


def get_used_variants(recipe_metadata):
    """because the functions in jinja_context don't directly used jinja variables, we need to teach
    conda-build which ones are used, so that it can limit the build space based on what entries are
    actually used."""
    with open(recipe_metadata.meta_path) as f:
        recipe_text = f.read()
    used_variables = set()
    for lang in 'c', 'cxx', 'fortran':
        if re.search('compiler\([\\]?[\'"]{}[\\]?[\'"]\)'.format(lang), recipe_text):
            used_variables.update(set(['{}_compiler'.format(lang), 'target_platform']))
    return used_variables
