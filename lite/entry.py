"""Windows GUI entry point with a diagnostic exit status for packaging checks."""

import sys
import traceback
from pathlib import Path

if __name__ == "__main__":
    try:
        from app import main

        sys.exit(main())
    except Exception:
        if len(sys.argv) == 3 and sys.argv[1] == "--smoke-test":
            Path(sys.argv[2]).write_text(traceback.format_exc(), encoding="utf-8")
            sys.exit(1)
        raise
