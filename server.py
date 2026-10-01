# -*- coding: utf-8 -*-
"""MaxPlan : lance le serveur.

    python server.py        puis ouvrir http://127.0.0.1:8765

Le code est dans le paquet maxplan/ (voir maxplan/__init__.py pour son organisation).
"""

import sys

try:  # console Windows : éviter UnicodeEncodeError sur les logs
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

from maxplan.serveur import main

if __name__ == "__main__":
    main()
