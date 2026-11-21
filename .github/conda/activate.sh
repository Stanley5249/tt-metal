# tt-metal reads kernel sources, firmware, and SOC descriptors under the
# runtime root, and Tracy's tools and viewer under TT_METAL_HOME.
export TT_METAL_RUNTIME_ROOT="${CONDA_PREFIX}/share/tt-metal/"
export TT_METAL_HOME="${CONDA_PREFIX}/share/tt-metal"
# The libraries need conda's newer libstdc++, but a PyPI wheel such as torch,
# imported first, would load the system's by soname, and the process keeps it.
export _TT_METAL_OLD_LD_LIBRARY_PATH="${LD_LIBRARY_PATH-}"
export LD_LIBRARY_PATH="${CONDA_PREFIX}/lib${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}"
