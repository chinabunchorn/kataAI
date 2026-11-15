"""Image-only entry point: explicitly add the immutable trusted module path."""

import sys

sys.path.insert(0, "/opt/kataai")
from runnerlib.supervisor import main

if __name__ == "__main__":
    raise SystemExit(main())
