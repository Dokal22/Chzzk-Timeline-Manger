"""Report whether this exact Python interpreter can run PyTorch on CUDA."""

import importlib.metadata
import subprocess
import sys


print(f"Python executable: {sys.executable}")
for package in ("torch", "torchaudio", "pyannote.audio", "faster-whisper"):
    try:
        print(f"{package}: {importlib.metadata.version(package)}")
    except importlib.metadata.PackageNotFoundError:
        print(f"{package}: not installed")

torch = None
try:
    import torch
except ImportError as exc:
    print(f"PyTorch import failed: {exc}")

if torch is not None:
    print(f"torch.__version__: {torch.__version__}")
    print(f"torch.version.cuda: {torch.version.cuda or 'CPU-only build'}")
    print(f"torch.cuda.is_available(): {torch.cuda.is_available()}")
    if torch.cuda.is_available():
        device = torch.device("cuda")
        value = torch.tensor([1.0, 2.0, 3.0], device=device)
        result = (value * 2).sum().item()
        torch.cuda.synchronize()
        print(f"CUDA device: {torch.cuda.get_device_name(0)}")
        print(f"CUDA tensor smoke result: {result:g}")
    else:
        print("CUDA tensor smoke: NOT RUN")

try:
    result = subprocess.run(
        ["nvidia-smi", "--query-gpu=name,driver_version,memory.total", "--format=csv,noheader"],
        check=True, capture_output=True, text=True,
    )
    print(f"nvidia-smi: {result.stdout.strip()}")
except (OSError, subprocess.CalledProcessError) as exc:
    print(f"nvidia-smi unavailable: {exc}")

if torch is None or not torch.cuda.is_available():
    raise SystemExit(1)
