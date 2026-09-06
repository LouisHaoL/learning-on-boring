"""支持 `python -m ripple <file.rip>`。"""

import sys

from .main import main

sys.exit(main(sys.argv))
