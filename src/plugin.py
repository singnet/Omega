"""
This is Omega internal API which is built on the top of the plugins API.
Most of the functions here calls corresponding functions of the registered
plugins.
"""

import importlib
import importlib.util
import logging
import pathlib
import sys
from types import ModuleType

import yaml

logger = logging.getLogger(__name__)

_LOADERS = ["python", "metta"]
_REPO = pathlib.Path(__file__).parent.parent.resolve()
_plugins = {}

def _error(func, text):
    error = f"{func}: {text}"
    logger.error(error)
    raise RuntimeError(error)

def listPlugins():
    """Loads the list of the plugins from ./config/plugins.yaml file and then
    returns list of triples (loader, name, location). YAML file
    contains the list of plugins each specified by three fields:
    - name - required, must be unique
    - loader - required, must be either "python" or "metta"
    - location - optional, path to the plugin module used by Python loader"""
    global _plugins, _REPO, _LOADERS

    config_path = _REPO.joinpath("./config/plugins.yaml")
    with open(config_path, "r") as f:
        yaml_content = yaml.safe_load(f)

    plugins = []
    for i, p in enumerate(yaml_content):
        name = p.get("name")
        if name is None:
            _error("listPlugins", f"name field is empty, file: {config_path}, index: {i}")
        if name in _plugins:
            _error("listPlugins", f"name '{name}' is not unique")

        loader = p.get("loader", "metta")
        if not loader in _LOADERS:
            _error("listPlugins", f"incorrect loader type '{loader}', only {_LOADERS} are supported")

        location = p.get("location")
        if location is not None:
            location = str(pathlib.Path(location.format(REPO=_REPO)).resolve())
        else:
            location = ""

        plugins.append([loader, name, location])

    return plugins

class PythonPlugin:
    """Class to wrap the reference to the Python module and keep it inside
    plugins registry"""

    def __init__(self, mod):
        self.mod = mod

def addLocationToPath(location):
    """Add a plugin's folder to sys.path so a plugin made of several files can
    import its own modules. Used by the Python loader for multi-file Python
    plugins, and by the MeTTa loader so a MeTTa plugin can py-call into its own
    .py file."""
    global _REPO
    sys.path.append(str(pathlib.Path(location.format(REPO=_REPO)).resolve()))


def _load_python_module(name: str, modpath: pathlib.Path) -> ModuleType:
    """Load a plugin file with shared module identity where possible."""
    cached = sys.modules.get(name)
    cached_file = getattr(cached, "__file__", None)
    if cached_file and pathlib.Path(cached_file).resolve() == modpath:
        return cached

    spec = importlib.util.spec_from_file_location(name, modpath)
    mod = importlib.util.module_from_spec(spec)
    cache_module = name not in sys.modules
    if cache_module:
        imported_spec = importlib.util.find_spec(name)
        cache_module = imported_spec is None or (
            imported_spec.origin is not None
            and pathlib.Path(imported_spec.origin).resolve() == modpath
        )
    if cache_module:
        sys.modules[name] = mod
    try:
        spec.loader.exec_module(mod)
    except BaseException:
        if cache_module:
            sys.modules.pop(name, None)
        raise
    return mod


def loadPythonPlugin(name: str, location: str | None) -> None:
    """Python plugin loader implementation. If location of the plugin is
    specified it imports "<location>/<name>.py" file. Imports <name> Python
    module otherwise. Calls "loadOmegaPlugin" function from the imported
    module. This is the point where plugin's code gets control and should
    register appropriate callbacks."""
    global _plugins, _REPO

    mod = None
    if not location:
        logger.info(f"_initPythonPlugin: loading {name} plugin from PYTHONPATH using Python module loader")
        mod = importlib.import_module(name)
    else:
        # adding location into sys.path to be able loading plugins which
        # consist of multiple files
        addLocationToPath(location)
        location = pathlib.Path(location.format(REPO=_REPO)).resolve()
        modpath = location.joinpath(f"{name}.py").resolve()
        logger.info(f"_initPythonPlugin: loading {name} plugin from {modpath} using Python module loader")
        mod = _load_python_module(name, modpath)

    if mod is not None:
        _plugins[name] = PythonPlugin(mod)
    else:
        _error("_initPythonPlugin", f"Couldn't find Python module {name}")

    if not hasattr(mod, "loadOmegaPlugin"):
        _error("_initPythonPlugin", f"No loadOmegaPlugin() function is implemented by plugin {name}")
    plugin_loader = getattr(mod, "loadOmegaPlugin")
    plugin_loader()
