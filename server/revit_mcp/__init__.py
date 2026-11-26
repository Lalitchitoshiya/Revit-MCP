"""Revit MCP server — bridges Claude (via MCP) to a running Autodesk Revit
session through the C# add-in's loopback socket.
"""

try:  # written by installer/build.ps1 from the repo's VERSION file
    from ._version import __version__
except ImportError:  # development checkout
    __version__ = "0.0.0-dev"
