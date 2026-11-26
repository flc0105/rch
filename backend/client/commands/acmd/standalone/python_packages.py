"""Inspect the current Client's Python packages and loaded modules."""
import importlib
import sys
from importlib import metadata

from client.commands.acmd.decorators import argument_command
from core.commands.argument_models import ArgumentCommandSpec, ArgumentOptionSpec
from core.utils.command_output import StructuredCommandResult, ResultDataShape


PYTHON_PACKAGES_SPEC = ArgumentCommandSpec(
    name='python_packages',
    description='Explore Python packages and modules',
    options=[
        ArgumentOptionSpec('loaded', 'flag', default=False, alias='l',
                           help_text='List distributions with loaded modules in the Client process'),
        ArgumentOptionSpec('import', 'str', default='', allow_empty=False,
                           help_text='Import and inspect an exact module or distribution name'),
        ArgumentOptionSpec('filter', 'str', default='', allow_empty=False,
                           help_text='Filter distribution names'),
        ArgumentOptionSpec('help', 'flag', default=False, help_text='Show this help message'),
    ],
    examples=[
        'acmd python_packages',
        'acmd python_packages -l --filter yaml --json',
        'acmd python_packages --import requests',
    ],
)


@argument_command('python_packages', spec=PYTHON_PACKAGES_SPEC)
def python_packages(self, args_dict):
    name = args_dict['import'].strip()
    keyword = args_dict['filter'].strip().casefold()
    loaded = args_dict['loaded']
    if args_dict.get('_args'):
        return 0, 'Use --import to inspect a Python module'
    if name and (loaded or keyword):
        return 0, '--import cannot be combined with --loaded or --filter'
    if name:
        result = StructuredCommandResult(status=1, data=_inspect_module(name),
                                         shape=ResultDataShape.FLAT, width=24,
                                         formats=('flat', 'kv', 'json'))
    elif loaded:
        known = metadata.packages_distributions()
        loaded_modules = {key.partition('.')[0] for key, module in sys.modules.copy().items() if module is not None}
        names = {dist_name for module in loaded_modules for dist_name in known.get(module, ())}
        names = sorted((item for item in names if keyword in item.casefold()), key=lambda item: (item.casefold(), item))
        rows = _distribution_rows(names)
        result = StructuredCommandResult(status=1, data=rows,
                                         shape=ResultDataShape.LINES, line_field='package',
                                         formats=('lines', 'table', 'records', 'json'))
    else:
        packages = {}
        for dist in metadata.distributions():
            name = str(dist.metadata.get('Name') or '').strip()
            if name and keyword in name.casefold():
                packages[name.casefold()] = {'package': name, 'version': str(dist.version or 'unknown')}
        rows = [packages[key] for key in sorted(packages)]
        result = StructuredCommandResult(status=1, data=rows, shape=ResultDataShape.LINES,
                                         line_field='package', formats=('lines', 'table', 'records', 'json'))
    if loaded and not names:
        result.message = 'No matching loaded distributions'
    return result


def _inspect_module(name):
    result = {
        'module': name, 'importable': False, 'module_path': None, 'module_version': None,
        'package_name': None, 'package_version': None, 'package_dependencies': [],
    }
    distribution = None
    try:
        try:
            module = importlib.import_module(name)
        except ModuleNotFoundError as exc:
            # A missing dependency inside the requested module is a real import failure.
            if exc.name != name:
                raise
            try:
                distribution = metadata.distribution(name)
            except metadata.PackageNotFoundError:
                raise exc from None

            package_name = distribution.metadata['Name'].casefold()
            candidates = sorted(
                module_name for module_name, packages in metadata.packages_distributions().items()
                if any(package.casefold() == package_name for package in packages)
            )
            if len(candidates) != 1:
                if candidates:
                    raise ImportError(f'Specify a module name: {", ".join(candidates)}') from None
                raise exc
            name = candidates[0]
            result['module'] = name
            module = importlib.import_module(name)
    except ImportError as exc:
        result['error'] = str(exc)
    else:
        result['importable'] = True
        result['module_path'] = getattr(module, '__file__', None)
        for attr in ('__version__', 'version', 'VERSION'):
            if hasattr(module, attr):
                result['module_version'] = str(getattr(module, attr))
                break
        if distribution is None:
            candidates = metadata.packages_distributions().get(name.split('.', 1)[0], [])
            if len(candidates) == 1:
                try:
                    distribution = metadata.distribution(candidates[0])
                except metadata.PackageNotFoundError:
                    pass

    if distribution is not None:
        result.update(package_name=distribution.metadata['Name'], package_version=distribution.version,
                      package_dependencies=list(distribution.requires or ()))
    return result


def _distribution_rows(names):
    rows = {}
    for name in names:
        try:
            dist = metadata.distribution(name)
        except metadata.PackageNotFoundError:
            continue
        canonical = str(dist.metadata.get('Name') or name).strip()
        if canonical:
            rows[canonical.casefold()] = {'package': canonical, 'version': str(dist.version or 'unknown')}
    return [rows[key] for key in sorted(rows)]
