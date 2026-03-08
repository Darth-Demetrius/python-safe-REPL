# Copilot Workspace Instructions

- Always use this workspace virtual environment for Python execution.
- The venv already exists, so do not create a new one.
- Use `python` to refer to the Python interpreter in the virtual environment.
- Prefer workspace-local tools and dependencies from `.venv`.
- This project has not been implemented yet, so do not worry about backwards compatibility.
- NEVER create compatibility shims or aliases during development. If a change breaks something, just fix the breakage.
- Allow changes to the API as needed during development.
- Follow the PEP 8 style guide for Python code.
- Write docstrings for all public functions and classes.
- Document any assumptions or decisions made during implementation in the code comments.
- NEVER add backward compatibility code.
- Avoid adding tiny helper functions that are only used once or twice. Just write the code inline where it's needed.
- If you find yourself writing a helper function, consider whether it would actually improve readability or if it would just add unnecessary indirection. If it's the latter, just write the code inline.
- Do not ever keep compatibility functions or aliases. If you need to change an API, just change it and fix any breakages. Do not add shims or aliases to preserve the old API.
- Do not keep old code around after it has been changed. If you change a function signature, just change all the call sites. Do not keep the old function around as an alias or shim.
