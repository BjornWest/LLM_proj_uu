"""Pinned-wheel CUDA paths, extracted from the prior Training experiment."""
from pathlib import Path


def compiler_environment(cuda_home, linker_dir, environment):
    """Expose the pinned wheel toolkit without modifying its installation."""
    cuda = Path(cuda_home)
    if not (cuda / "bin/nvcc").is_file() or not (cuda / "lib/libcudart.so.13").is_file():
        raise ValueError("Pinned CUDA compiler/runtime wheel files are missing")
    linker = Path(linker_dir)
    linker.mkdir(parents=True, exist_ok=True)
    name = linker / "libcudart.so"
    target = (cuda / "lib/libcudart.so.13").resolve()
    if name.exists() or name.is_symlink():
        if not name.is_symlink() or name.resolve() != target:
            raise ValueError("Private CUDA linker name has an unexpected target")
    else:
        name.symlink_to(target)
    env = dict(environment)
    env["CUDA_HOME"] = str(cuda)
    env["PATH"] = str(cuda / "bin") + ":" + env.get("PATH", "")
    env["LIBRARY_PATH"] = str(linker) + ":" + str(cuda / "lib") + ":" + env.get("LIBRARY_PATH", "")
    env["LD_LIBRARY_PATH"] = str(cuda / "lib") + ":" + env.get("LD_LIBRARY_PATH", "")
    return env
