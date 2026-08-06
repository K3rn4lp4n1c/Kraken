from . import carpenter, PLUGINS

def _get_plugins(offset: int = 0, limit: int = 10) -> list[dict]:
    """
    Fetch all available plugins.

    Returns:
        list[dict]: A list of dictionaries, each representing a plugin with its details.
    """
    plugins = sorted(PLUGINS.values(), key=lambda p: p.name)
    plugins = plugins[offset:offset + limit]
    return [
        {"name": plugin.name, "description": plugin.description, "tags": plugin.tags}
        for plugin in plugins
    ]

@carpenter.tool()
def get_plugins(offset: int = 0, limit: int = 10) -> dict:
    """
    Fetch all available plugins with pagination support in alphabetical order by name.

    Args:
        offset (int = 0): The starting index for pagination.
        limit (int = 10): The maximum number of plugins to return.
    Returns:
        dict: Contains `success`, `message`, and `plugins`.
        Each plugin item includes `name`, `description`, and `tags`.
    """
    plugins = _get_plugins(offset, limit)
    return {"success": True, "message": "Plugins fetched successfully.", "plugins": plugins}