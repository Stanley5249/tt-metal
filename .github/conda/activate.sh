# tt-metal reads kernel sources, firmware, and SOC descriptors under the
# runtime root, and Tracy's tools and viewer under TT_METAL_HOME. The libraries
# need conda's newer libstdc++, but a PyPI wheel such as torch, imported first,
# would load the system's by soname, and the process keeps it. Deactivation
# restores what each variable held before.
for _tt_metal_var in TT_METAL_RUNTIME_ROOT TT_METAL_HOME LD_LIBRARY_PATH; do
    if eval "[ -n \"\${${_tt_metal_var}+x}\" ]"; then
        eval "export _TT_METAL_SAVED_${_tt_metal_var}=\"\${${_tt_metal_var}}\""
    fi
done
unset _tt_metal_var
export TT_METAL_RUNTIME_ROOT="${CONDA_PREFIX}/share/tt-metal/"
export TT_METAL_HOME="${CONDA_PREFIX}/share/tt-metal"
export LD_LIBRARY_PATH="${CONDA_PREFIX}/lib${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}"
