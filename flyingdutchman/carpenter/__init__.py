LOGGER_HANDLER_MARKER = "flyingdutchman_logging_handler"
from fastmcp import FastMCP

carpenter = FastMCP(name="Carpenter")

from .utils import *
from .extensions import *
from .plugins import *
from .tools import *