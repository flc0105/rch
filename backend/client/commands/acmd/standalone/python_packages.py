"""Inspect the current Client's Python packages and loaded modules."""
import importlib
import sys
from importlib import metadata

from client.commands.acmd.decorators import argument_command
from core.commands.argument_models import ArgumentCommandSpec, ArgumentOptionSpec
from core.utils.command_output import StructuredCommandResult, render_structured_result


PYTHON_PACKAGES_SPEC = ArgumentCommandSpec(
    name='python_packages',
    description='Inspect installed Python packages, loaded modules, or an individual import',
    options=[
        ArgumentOptionSpec('loaded', 'flag', default=False, alias='l',
                           help_text='List third-party modules loaded in the Client process'),
        ArgumentOptionSpec('name', 'str', default='', alias='n', allow_empty=False,
                           help_text='Import and inspect an exact module or distribution name'),
        ArgumentOptionSpec('filter', 'str', default='', allow_empty=False,
                           help_text='Filter installed packages or loaded modules by name'),
        ArgumentOptionSpec('json', 'flag', default=False, help_text='Output as JSON'),
        ArgumentOptionSpec('help', 'flag', default=False, help_text='Show this help message'),
    ],
    examples=[
        'acmd python_packages',
        'acmd python_packages -l --filter yaml --json',
        'acmd python_packages -n requests',
    ],
)


@argument_command('python_packages', spec=PYTHON_PACKAGES_SPEC)
def python_packages(self, args_dict):
    name = args_dict['name'].strip()
    keyword = args_dict['filter'].strip().casefold()
    loaded = args_dict['loaded']
    if args_dict.get('_args'):
        return 0, 'Use --name or -n to inspect a Python module'
    if name and (loaded or keyword):
        return 0, '--name cannot be combined with --loaded or --filter'
    output = 'json' if args_dict['json'] else 'text'

    if name:
        result = StructuredCommandResult(status=1, data=_inspect_module(name), shape='dict', width=24)
    elif loaded:
        snapshot = sys.modules.copy()
        known = metadata.packages_distributions()
        names = {key.partition('.')[0] for key, module in snapshot.items() if module is not None}
        names = sorted((name for name in names if name in known and keyword in name.casefold()),
                       key=lambda name: (name.casefold(), name))
        if output == 'text':
            return 1, '\n'.join(names) or 'No matching loaded third-party modules'
        result = StructuredCommandResult(status=1, data=[{'module': name} for name in names], shape='table')
    else:
        packages = {}
        for dist in metadata.distributions():
            name = str(dist.metadata.get('Name') or '').strip()
            if name and keyword in name.casefold():
                packages[name.casefold()] = {'package': name, 'version': str(dist.version or 'unknown')}
        rows = [packages[key] for key in sorted(packages)]
        result = StructuredCommandResult(status=1, data=rows, shape='table')
    return render_structured_result(result, output_format=output)


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
