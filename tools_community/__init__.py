# INTI — Community Tools
# ================================
# This directory contains tools created by the constellation itself
# or installed by users as plugins.
#
# Structure:
#   tools_community/
#   ├── __init__.py          ← This file
#   ├── .env.tools           ← API keys for third-party services
#   └── <tool_name>.py       ← Individual tool modules
#
# Each tool should follow the same pattern as core tools:
#   - Define a class or set of functions
#   - Register with ToolRegistry
#   - Specify risk level (LOW, HIGH, CRITICAL)
#
# The constellation can create new tools here autonomously.
# Users can also add their own tools and share them.
