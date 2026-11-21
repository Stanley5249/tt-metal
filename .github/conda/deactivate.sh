for _tt_metal_var in TT_METAL_RUNTIME_ROOT TT_METAL_HOME LD_LIBRARY_PATH; do
    if eval "[ -n \"\${_TT_METAL_SAVED_${_tt_metal_var}+x}\" ]"; then
        eval "export ${_tt_metal_var}=\"\${_TT_METAL_SAVED_${_tt_metal_var}}\""
        unset "_TT_METAL_SAVED_${_tt_metal_var}"
    else
        unset "${_tt_metal_var}"
    fi
done
unset _tt_metal_var
