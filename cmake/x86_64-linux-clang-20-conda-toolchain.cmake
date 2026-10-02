# Clang 20 and libstdc++ from a conda environment, such as the pixi workspace in
# pixi.toml. The libstdcpp toolchain looks for ld.lld-20, which conda-forge does
# not ship under that name.
set(CMAKE_C_COMPILER clang-20 CACHE INTERNAL "C compiler")
set(CMAKE_CXX_COMPILER clang++-20 CACHE INTERNAL "C++ compiler")
set(ENABLE_LIBCXX FALSE CACHE INTERNAL "Using clang's libc++")
set(CMAKE_LINKER_TYPE LLD)
# conda's clang config adds -Wl,-rpath to the environment on every link. The
# install step's RPATH_CHECK deletes any library whose RPATH differs from the
# expected one, which is the file being installed. Link without the default
# config; the environment's LD_LIBRARY_PATH covers runtime.
set(_env "$ENV{CONDA_PREFIX}")
set(_link_flags "--no-default-config --sysroot=${_env}/x86_64-conda-linux-gnu/sysroot")
string(APPEND _link_flags " -L${_env}/lib -Wl,-rpath-link,${_env}/lib")
foreach(kind EXE SHARED MODULE)
    set(CMAKE_${kind}_LINKER_FLAGS "${_link_flags}" CACHE STRING "" FORCE)
endforeach()
