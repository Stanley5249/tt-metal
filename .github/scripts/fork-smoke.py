"""Run one ttnn op on ttsim and compare it with torch.

fork-validate's smoke job runs it in the pixi wheel environment, after
installing the built wheel and `just fetch-ttsim`. It runs as a file, not with
`python -c`, so `import ttnn` finds the installed wheel instead of the ttnn/
folder in the checkout.
"""

import torch

# tt-vllm-tracer imports tt_transformers through models.common, which needs
# every package the wheel ships beside ttnn.
import models.common.utility_functions  # noqa: F401
import ttnn

device = ttnn.open_device(device_id=0)
try:
    a = torch.rand(32, 32, dtype=torch.bfloat16)
    t = ttnn.from_torch(a, layout=ttnn.TILE_LAYOUT, device=device)
    out = ttnn.to_torch(ttnn.add(t, t))
finally:
    ttnn.close_device(device)
torch.testing.assert_close(out, a + a)
print("ttnn.add matches torch on ttsim")
