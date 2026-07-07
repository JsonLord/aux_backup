#!/bin/bash
python -c "import os, gradio; path=os.path.join(os.path.dirname(gradio.__file__), 'components', 'base.py'); c=open(path).read(); open(path, 'w').write(c.replace('getattr(self, value)', 'getattr(self, value) if value != \"__provides__\" else None'))"
python app.py
# Trigger upload
