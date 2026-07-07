#!/bin/bash
# Patch Gradio to avoid AttributeError: __provides__ with zope.interface
python -c "import os, gradio.components.base as b; path=b.__file__; c=open(path).read(); open(path, 'w').write(c.replace('if callable(getattr(self, value))', 'if value != \"__provides__\" and callable(getattr(self, value))').replace('getattr(self, value)', '(getattr(self, value) if value != \"__provides__\" else None)'))"

# Patch Gradio Client to avoid TypeError in schema generation
python -c "import os, gradio_client.utils as u; path=u.__file__; c=open(path).read(); open(path, 'w').write(c.replace('if \"const\" in schema:', 'if isinstance(schema, dict) and \"const\" in schema:').replace('if \"enum\" in schema:', 'if isinstance(schema, dict) and \"enum\" in schema:'))"

# Start the app
python app.py
