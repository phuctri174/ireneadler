import os

# No network at runtime. Kokoro's weights resolve through huggingface_hub, which
# otherwise HEADs huggingface.co on every start to check for updates. Set before
# anything imports it; weights come from the local cache populated at setup.
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"

# The tool registry lives at the repo root (tools/), beside core/ and hud/.
import sys
from pathlib import Path

_ROOT = str(Path(__file__).resolve().parents[2])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
