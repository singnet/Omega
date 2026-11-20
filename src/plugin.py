"""
This is Omega internal API which is built on the top of the plugins API.
Most of the functions here calls corresponding functions of the registered
plugins.
"""

import pathlib
import yaml
import importlib
import importlib.util
import sys
import logging
from config import config_get_by_key

logger = logging.getLogger(__name__)

_LOADERS = ["python", "metta"]
_REPO = pathlib.Path(__file__).parent.parent.resolve()
_plugins = {}

def _error(func, text):
    error = f"{func}: {text}"
    logger.error(error)
    raise RuntimeError(error)

def parsePluginConfig(config_path):
    """Parses the plugin config and returns a list of triples (loader, name, location)"""
    global _plugins, _REPO, _LOADERS

    try:
        with open(config_path, "r") as f:
            yaml_content = yaml.safe_load(f)
    except Exception as e:
        _error("parsePluginConfig", f"failed to read {config_path}: {repr(e)}")
    if not isinstance(yaml_content, list):
        _error(
            "parsePluginConfig",
            f"invalid plugin config format in {config_path}: expected a list of plugins"
        )
    if not yaml_content:
        logger.warning(
            f"parsePluginConfig: plugin config {config_path} is empty. "
            "This file declares no plugins and will be skipped."
        )

    name_set = set()
    plugins = []
    for i, p in enumerate(yaml_content):
        if not isinstance(p, dict):
            _error(
                "parsePluginConfig",
                f"invalid plugin config format in {config_path}: expected a dict for each plugin, got {type(p)} at index {i}"
            )
        name = p.get("name")
        if not name or not str(name).strip():
            _error(
                "parsePluginConfig",
                f"'name' field is empty, file: {config_path}, index: {i}"
            )
        if not isinstance(name, str):
            _error(
                "parsePluginConfig",
                f"'name' field is not a string, file: {config_path}, index: {i}"
            )
        if name in _plugins or name.casefold() in name_set:
            _error(
                "parsePluginConfig",
                f"name '{name}' is not unique, file: {config_path}, index: {i}"
            )
        name_set.add(name.casefold())

        loader = p.get("loader")
        if not loader in _LOADERS:
            _error(
                "parsePluginConfig",
                f"plugin '{name}' requires a 'loader' from {_LOADERS}, "
                f"got {loader!r}, file: {config_path}, index: {i}"
            )

        location = p.get("location")
        if location is not None:
            if not isinstance(location, str):
                _error(
                    "parsePluginConfig",
                    f"'location' must be a string for plugin '{name}', "
                    f"file: {config_path}, index: {i}"
                )
            location = str(pathlib.Path(location.format(REPO=_REPO)).resolve())
        else:
            location = ""

        plugins.append([loader, name, location])

    return plugins

def listPlugins():
    """Loads plugins from config/plugins.yaml and customPluginsConfigPath, then
    returns list of triples (loader, name, location). YAML file
    contains the list of plugins each specified by three fields:
    - name - required, must be unique
    - loader - required, must be either "python" or "metta"
    - location - optional, path to the plugin module used by Python loader"""
    global _REPO

    core_plugins_config_path = _REPO.joinpath("./config/plugins.yaml")
    custom_plugins_config_path = config_get_by_key("customPluginsConfigPath")

    core_plugins = parsePluginConfig(core_plugins_config_path)
    if custom_plugins_config_path:
        custom_plugins = parsePluginConfig(custom_plugins_config_path)
    else:
        custom_plugins = []

    core_names = {p[1].casefold() for p in core_plugins}
    for _, name, _ in custom_plugins:
        if name.casefold() in core_names:
            _error(
                "listPlugins",
                f"custom plugin '{name}' in {custom_plugins_config_path} "
                f"conflicts with core plugin in {core_plugins_config_path}"
            )

    return core_plugins + custom_plugins

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

def loadPythonPlugin(name, location):
    """Python plugin loader implementation. If location of the plugin is
    specified it imports "<location>/<name>.py" file. Imports <name> Python
    module otherwise. Calls "loadOmegaPlugin" function from the imported
    module. This is the point where plugin's code gets control and should
    register appropriate callbacks. Repeated loads of the same module do not
    call the entry point again."""
    global _plugins, _REPO

    mod = None
    if not location:
        logger.info(f"_initPythonPlugin: loading {name} plugin from PYTHONPATH using Python module loader")
        mod = importlib.import_module(name)
    else:
        location = pathlib.Path(location.format(REPO=_REPO)).resolve()
        modpath = location.joinpath(f"{name}.py").resolve()
        logger.info(f"_initPythonPlugin: loading {name} plugin from {modpath} using Python module loader")
        if name in sys.modules:
            mod = sys.modules[name]
            existing_path = getattr(mod, "__file__", None)
            if existing_path is None or pathlib.Path(existing_path).resolve() != modpath:
                _error("_initPythonPlugin", f"Plugin name '{name}' is already used by another module ({existing_path}); cannot load {modpath}")
        else:
            # Also protect dependencies that are importable but not loaded yet.
            existing_spec = importlib.util.find_spec(name)
            if existing_spec is not None:
                existing_path = existing_spec.origin
                if existing_path is None or existing_path in ("built-in", "frozen") or pathlib.Path(existing_path).resolve() != modpath:
                    _error("_initPythonPlugin", f"Plugin name '{name}' is already used by another importable module ({existing_path}); cannot load {modpath}; choose a different plugin name")

        # Multi-file plugins need their folder available for sibling imports.
        if str(location) not in sys.path:
            addLocationToPath(str(location))
        if mod is None:
            spec = importlib.util.spec_from_file_location(name, modpath)
            mod = importlib.util.module_from_spec(spec)
            # Match normal import semantics, including imports during execution.
            sys.modules[name] = mod
            try:
                spec.loader.exec_module(mod)
            except BaseException:
                if sys.modules.get(name) is mod:
                    del sys.modules[name]
                raise

    if mod is None:
        _error("_initPythonPlugin", f"Couldn't find Python module {name}")

    if name in _plugins:
        if _plugins[name].mod is mod:
            return
        _error("_initPythonPlugin", f"Plugin name '{name}' is already registered with another module")

    if not hasattr(mod, "loadOmegaPlugin"):
        _error("_initPythonPlugin", f"No loadOmegaPlugin() function is implemented by plugin {name}")
    plugin_loader = getattr(mod, "loadOmegaPlugin")
    _plugins[name] = PythonPlugin(mod)
    try:
        plugin_loader()
    except BaseException:
        del _plugins[name]
        raise
