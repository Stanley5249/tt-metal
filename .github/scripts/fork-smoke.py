"""Run two ttnn ops on ttsim and compare them with torch.

fork-validate's smoke job runs it in the pixi wheel environment, after
installing the built wheel and `just fetch-ttsim`. It runs as a file, not with
`python -c`, so `import ttnn` finds the installed wheel instead of the ttnn/
folder in the checkout.

The matmul spreads over a 2x2 core grid and multicasts its inputs, so NoC
tracing records reads, multicasts, and the profiler's mid-kernel quick_push.
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

    x = torch.rand(64, 64, dtype=torch.bfloat16)
    y = torch.rand(64, 64, dtype=torch.bfloat16)
    tx = ttnn.from_torch(x, layout=ttnn.TILE_LAYOUT, device=device)
    ty = ttnn.from_torch(y, layout=ttnn.TILE_LAYOUT, device=device)
    product = ttnn.to_torch(ttnn.matmul(tx, ty))
finally:
    ttnn.close_device(device)
torch.testing.assert_close(out, a + a)
print("ttnn.add matches torch on ttsim")
torch.testing.assert_close(product.float(), x.float() @ y.float(), rtol=0.05, atol=0.5)
print("ttnn.matmul matches torch on ttsim")
