"""Checks that the GPU security policy stays in sync with the default one.

The GPU policy is a copy of the default policy with the paths the NVIDIA
driver needs. Both files are maintained by hand, so this test pins the
difference between them and fails when only one of the two is updated.
"""
import pathlib
import yaml

_PROFILE_DIR = pathlib.Path(__file__).parent.parent / "profile"
_DEFAULT_POLICY_PATH = _PROFILE_DIR / "policy.yaml"
_GPU_POLICY_PATH = _PROFILE_DIR / "policy-gpu.yaml"

# The CUDA driver writes /proc/self/task/<tid>/comm, so the GPU policy moves
# /proc from read-only to read-write access.
_MOVED_TO_READ_WRITE = ["/proc"]
_GPU_READ_ONLY = [
    "/run/nvidia-persistenced",
    "/sys/bus/pci",
    "/sys/class/drm",
    "/sys/devices/pci*",
    "/usr/lib/wsl",
]
_GPU_READ_WRITE = [
    "/dev/dxg",
    "/dev/nvidia-modeset",
    "/dev/nvidia-uvm",
    "/dev/nvidia-uvm-tools",
    "/dev/nvidia[0-9]*",
    "/dev/nvidiactl",
]


def _load(path):
    with open(path, "r") as f:
        return yaml.safe_load(f)


def test_gpu_policy_matches_default_policy_plus_gpu_paths():
    default = _load(_DEFAULT_POLICY_PATH)
    gpu = _load(_GPU_POLICY_PATH)

    assert gpu["version"] == default["version"]
    assert gpu["landlock"] == default["landlock"]

    default_fs = default["filesystem_policy"]
    gpu_fs = gpu["filesystem_policy"]
    assert gpu_fs["include_workdir"] == default_fs["include_workdir"]

    expected_read_only = (set(default_fs["read_only"])
                          - set(_MOVED_TO_READ_WRITE)
                          | set(_GPU_READ_ONLY))
    expected_read_write = (set(default_fs["read_write"])
                           | set(_MOVED_TO_READ_WRITE)
                           | set(_GPU_READ_WRITE))

    assert set(gpu_fs["read_only"]) == expected_read_only
    assert set(gpu_fs["read_write"]) == expected_read_write
