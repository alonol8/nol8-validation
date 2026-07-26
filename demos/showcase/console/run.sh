#!/usr/bin/env bash
# Launch the NOL8 Live Demo Console on the box that reaches the engines (nol8-demo).
#
#   ssh nol8-demo
#   cd /opt/nol8/nol8-validation && bash demos/showcase/console/run.sh
#
# Then, from your laptop, tunnel and open a browser:
#   ssh -f -N -L 8770:localhost:8770 nol8-demo   # -f -N backgrounds the tunnel
#   open http://localhost:8770
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$ROOT"
source .venv/bin/activate
set -a; source config/demo.env; source .env; set +a
export PATH="$HOME/.local/go/bin:$PATH"
exec python demos/showcase/console/server.py
