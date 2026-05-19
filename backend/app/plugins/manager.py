import importlib.util
import json
import logging
from pathlib import Path

from app.plugins.base import BasePlugin, PluginContext, PluginTool

logger = logging.getLogger(__name__)

PLUGINS_DIR = Path("./data/plugins")


class PluginManager:
    def __init__(self):
        self._plugins: dict[str, BasePlugin] = {}
        self._contexts: dict[str, PluginContext] = {}
        self._tools: dict[str, PluginTool] = {}

    def discover_plugins(self) -> list[str]:
        """Find all installed plugins."""
        PLUGINS_DIR.mkdir(parents=True, exist_ok=True)
        plugins = []
        for plugin_dir in PLUGINS_DIR.iterdir():
            if plugin_dir.is_dir() and (plugin_dir / "plugin.py").exists():
                plugins.append(plugin_dir.name)
        return plugins

    async def activate_plugin(self, plugin_name: str, project_path: str) -> bool:
        """Load and activate a plugin."""
        plugin_dir = PLUGINS_DIR / plugin_name
        plugin_file = plugin_dir / "plugin.py"
        manifest_file = plugin_dir / "manifest.json"

        if not plugin_file.exists():
            logger.error(f"Plugin not found: {plugin_name}")
            return False

        try:
            spec = importlib.util.spec_from_file_location(f"plugin_{plugin_name}", str(plugin_file))
            if spec is None or spec.loader is None:
                logger.error(f"Could not load plugin {plugin_name}: no loader found")
                return False
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            plugin_class = None
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if isinstance(attr, type) and issubclass(attr, BasePlugin) and attr is not BasePlugin:
                    plugin_class = attr
                    break

            if not plugin_class:
                logger.error(f"No BasePlugin subclass found in {plugin_name}")
                return False

            plugin = plugin_class()

            if manifest_file.exists():
                manifest_data = json.loads(manifest_file.read_text(encoding="utf-8"))
                from app.plugins.base import PluginManifest
                plugin.manifest = PluginManifest(**manifest_data)

            context = PluginContext(project_path)
            await plugin.on_activate(context)

            self._plugins[plugin_name] = plugin
            self._contexts[plugin_name] = context

            for tool in plugin.get_tools():
                self._tools[tool.name] = tool
                logger.info(f"Registered tool: {tool.name} from plugin {plugin_name}")

            return True

        except Exception as e:
            logger.error(f"Failed to activate plugin {plugin_name}: {e}")
            return False

    async def deactivate_plugin(self, plugin_name: str) -> bool:
        """Deactivate and unload a plugin."""
        if plugin_name not in self._plugins:
            return False
        plugin = self._plugins[plugin_name]
        await plugin.on_deactivate()
        del self._plugins[plugin_name]
        del self._contexts[plugin_name]
        return True

    def get_all_tools(self) -> list[PluginTool]:
        return list(self._tools.values())

    def get_tool(self, name: str) -> PluginTool | None:
        return self._tools.get(name)

    def list_active_plugins(self) -> list[dict]:
        result = []
        for name, plugin in self._plugins.items():
            m = getattr(plugin, 'manifest', None)
            result.append({
                "name": getattr(m, 'name', name),
                "version": getattr(m, 'version', "0.0.0"),
                "description": getattr(m, 'description', ""),
                "tools": [t.name for t in plugin.get_tools()],
            })
        return result


plugin_manager = PluginManager()
