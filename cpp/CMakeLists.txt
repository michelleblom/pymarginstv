cmake_minimum_required(VERSION 3.22)
project(marginstv LANGUAGES C CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release)
endif()

# Results must match the Python program bit for bit, so the compiler may
# not fuse a multiply and an add into one instruction or reorder float maths.
add_compile_options(-ffp-contract=off -fno-fast-math)
set(CMAKE_CXX_FLAGS_RELEASE "-O3")
set(CMAKE_CXX_FLAGS_RELWITHDEBINFO "-O2 -g")

option(MARGINSTV_SANITIZE "Sanitizer to build with: address, thread, undefined, or empty" "")
if(MARGINSTV_SANITIZE)
  add_compile_options(-fsanitize=${MARGINSTV_SANITIZE} -fno-omit-frame-pointer)
  add_link_options(-fsanitize=${MARGINSTV_SANITIZE})
endif()

find_package(ZLIB REQUIRED)
include(FetchContent)

# oneTBB and simdjson: use installed copies when recent enough, otherwise
# download and build them with the program (older Linux releases ship an
# old TBB and no simdjson). MARGINSTV_FETCH_DEPS=ON always downloads.
option(MARGINSTV_FETCH_DEPS "Download oneTBB and simdjson instead of using installed ones" OFF)
if(NOT MARGINSTV_FETCH_DEPS)
  find_package(TBB 2021 QUIET)
  find_package(simdjson QUIET)
endif()
if(NOT TBB_FOUND)
  message(STATUS "oneTBB: downloading v2022.3.0")
  set(TBB_TEST OFF CACHE BOOL "" FORCE)
  set(TBB_STRICT OFF CACHE BOOL "" FORCE)
  set(TBB_EXAMPLES OFF CACHE BOOL "" FORCE)
  FetchContent_Declare(onetbb GIT_REPOSITORY https://github.com/uxlfoundation/oneTBB.git
                       GIT_TAG v2022.3.0 GIT_SHALLOW TRUE)
  FetchContent_MakeAvailable(onetbb)
endif()
if(NOT simdjson_FOUND)
  message(STATUS "simdjson: downloading v3.10.1")
  FetchContent_Declare(simdjson GIT_REPOSITORY https://github.com/simdjson/simdjson.git
                       GIT_TAG v3.10.1 GIT_SHALLOW TRUE)
  FetchContent_MakeAvailable(simdjson)
endif()

# GCC before 11 lacks parts of C++20 this code uses (floating-point
# std::to_chars among them).
if(CMAKE_CXX_COMPILER_ID STREQUAL "GNU" AND CMAKE_CXX_COMPILER_VERSION VERSION_LESS 11)
  message(FATAL_ERROR "GCC ${CMAKE_CXX_COMPILER_VERSION} is too old: GCC 11 or newer is needed. "
                      "Point CXX and CC at a newer compiler, e.g. CXX=g++-11 CC=gcc-11.")
endif()

# ---------------------------------------------------------------- SCIP
# The program links the very SCIP library that pyscipopt runs on this
# machine, so MINLP solves follow the same path as in the Python program.
# pyscipopt's wheels bundle SCIP with SoPlex, Ipopt and MUMPS. The headers
# come from the SCIP source release of the same version, fetched here.
execute_process(
  COMMAND python3 -c "import pyscipopt, os; print(os.path.dirname(pyscipopt.__file__))"
  OUTPUT_VARIABLE PYSCIPOPT_DIR OUTPUT_STRIP_TRAILING_WHITESPACE)
execute_process(
  COMMAND python3 -c "from pyscipopt import Model; m = Model(); print(f'{m.getMajorVersion()};{m.getMinorVersion()};{m.getTechVersion()}')"
  OUTPUT_VARIABLE PYSCIP_VERSION OUTPUT_STRIP_TRAILING_WHITESPACE)
if(NOT PYSCIPOPT_DIR OR NOT PYSCIP_VERSION)
  message(FATAL_ERROR "pyscipopt not found for python3: it supplies the SCIP library")
endif()
list(GET PYSCIP_VERSION 0 SCIP_VERSION_MAJOR)
list(GET PYSCIP_VERSION 1 SCIP_VERSION_MINOR)
list(GET PYSCIP_VERSION 2 SCIP_VERSION_PATCH)
set(SCIP_TAG "v${SCIP_VERSION_MAJOR}.${SCIP_VERSION_MINOR}.${SCIP_VERSION_PATCH}")
message(STATUS "pyscipopt runs SCIP ${SCIP_TAG}")

set(SCIP_SOURCE_DIR "" CACHE PATH "SCIP source of the same version (fetched when empty)")
if(NOT SCIP_SOURCE_DIR)
  # SOURCE_SUBDIR points at a folder with no CMakeLists.txt, so the
  # source is downloaded for its headers and SCIP itself is not built.
  FetchContent_Declare(scip_src GIT_REPOSITORY https://github.com/scipopt/scip.git
                       GIT_TAG ${SCIP_TAG} GIT_SHALLOW TRUE SOURCE_SUBDIR headers-only)
  FetchContent_MakeAvailable(scip_src)
  set(SCIP_SOURCE_DIR "${scip_src_SOURCE_DIR}")
endif()
file(STRINGS "${SCIP_SOURCE_DIR}/CMakeLists.txt" api_line REGEX "set\\(SCIP_VERSION_API")
string(REGEX MATCH "[0-9]+" SCIP_VERSION_API "${api_line}")
set(SCIP_CONFIG_DIR "${CMAKE_BINARY_DIR}/scip-config")
configure_file(cmake/scip_config.h.in "${SCIP_CONFIG_DIR}/scip/config.h" @ONLY)
configure_file(cmake/scip_export.h "${SCIP_CONFIG_DIR}/scip/scip_export.h" COPYONLY)

# Where the wheel keeps the library: .dylibs inside the package on macOS,
# pyscipopt.libs beside it on Linux.
set(SCIP_LIB_OUT "${CMAKE_BINARY_DIR}/lib")
file(MAKE_DIRECTORY "${SCIP_LIB_OUT}")
if(APPLE)
  file(GLOB scip_bundle "${PYSCIPOPT_DIR}/.dylibs/*.dylib")
  # The bundled library records an install path that does not exist on this
  # machine. Copy it next to the build output, point its id at @rpath, and
  # re-sign it (macOS rejects a modified library otherwise).
  foreach(lib ${scip_bundle})
    get_filename_component(name "${lib}" NAME)
    if(NOT EXISTS "${SCIP_LIB_OUT}/${name}")
      file(COPY "${lib}" DESTINATION "${SCIP_LIB_OUT}")
      execute_process(COMMAND install_name_tool -id "@rpath/${name}" "${SCIP_LIB_OUT}/${name}"
                      ERROR_QUIET)
      execute_process(COMMAND codesign -f -s - "${SCIP_LIB_OUT}/${name}" ERROR_QUIET OUTPUT_QUIET)
    endif()
  endforeach()
  file(GLOB SCIP_LIBRARY_FOUND "${SCIP_LIB_OUT}/libscip*.dylib")
  set(SCIP_RPATH "${SCIP_LIB_OUT}")
else()
  file(GLOB SCIP_LIBRARY_FOUND "${PYSCIPOPT_DIR}/../pyscipopt.libs/libscip*.so*"
                               "${PYSCIPOPT_DIR}/.libs/libscip*.so*")
  if(SCIP_LIBRARY_FOUND)
    list(GET SCIP_LIBRARY_FOUND 0 first)
    get_filename_component(SCIP_RPATH "${first}" DIRECTORY)
  endif()
endif()
set(SCIP_LIBRARY "" CACHE FILEPATH "SCIP shared library to link (found from pyscipopt when empty)")
if(NOT SCIP_LIBRARY)
  if(NOT SCIP_LIBRARY_FOUND)
    message(FATAL_ERROR "No libscip found in the pyscipopt install; set SCIP_LIBRARY")
  endif()
  list(GET SCIP_LIBRARY_FOUND 0 SCIP_LIBRARY)
else()
  get_filename_component(SCIP_RPATH "${SCIP_LIBRARY}" DIRECTORY)
endif()
message(STATUS "Linking SCIP library ${SCIP_LIBRARY}")

add_library(scip SHARED IMPORTED)
set_target_properties(scip PROPERTIES
  IMPORTED_LOCATION "${SCIP_LIBRARY}"
  INTERFACE_INCLUDE_DIRECTORIES "${SCIP_CONFIG_DIR};${SCIP_SOURCE_DIR}/src")

# ---------------------------------------------------------------- library
add_library(marginstv_core STATIC
  src/pynum.cpp
  src/pyset.cpp
  src/blake2b.cpp
  src/election.cpp
  src/simulate.cpp
  src/prefix.cpp
  src/bounds_eqlb.cpp
  src/bounds_disp.cpp
  src/pyexpr.cpp
  src/distance.cpp
  src/frontier.cpp
  src/search.cpp
  src/options.cpp
  src/logger.cpp)
target_include_directories(marginstv_core PUBLIC include)
target_link_libraries(marginstv_core PUBLIC TBB::tbb simdjson::simdjson scip)
target_compile_options(marginstv_core PRIVATE -Wall -Wextra -Wpedantic)

# SCIP's headers replace many calls with direct struct access when NDEBUG
# is set. Those structs depend on how the library was built, so the file
# that talks to SCIP always goes through the real functions instead.
set_source_files_properties(src/distance.cpp PROPERTIES COMPILE_OPTIONS "-UNDEBUG")

add_executable(marginstv app/main.cpp)
target_link_libraries(marginstv PRIVATE marginstv_core)
set_target_properties(marginstv PROPERTIES BUILD_RPATH "${SCIP_RPATH}")

# ---------------------------------------------------------------- tests
option(MARGINSTV_TESTS "Build the C++ tests" ON)
set(MARGINSTV_DATA_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../../stv-rla/data" CACHE PATH
    "Election data folder the tests read")
if(MARGINSTV_TESTS)
  FetchContent_Declare(Catch2
    GIT_REPOSITORY https://github.com/catchorg/Catch2.git
    GIT_TAG v3.5.4)
  FetchContent_MakeAvailable(Catch2)

  add_executable(marginstv_tests
    tests/unit/golden.cpp
    tests/unit/test_pyformat.cpp
    tests/unit/test_pyset.cpp
    tests/unit/test_prefix.cpp
    tests/unit/test_inputs.cpp
    tests/replay/test_replay.cpp
    tests/scip/test_models.cpp)
  target_link_libraries(marginstv_tests PRIVATE marginstv_core Catch2::Catch2WithMain ZLIB::ZLIB)
  target_compile_definitions(marginstv_tests PRIVATE
    MARGINSTV_GOLDEN_DIR="${CMAKE_CURRENT_SOURCE_DIR}/tests/golden/data"
    MARGINSTV_DATA_DIR="${MARGINSTV_DATA_DIR}"
    MARGINSTV_REPO_DIR="${CMAKE_CURRENT_SOURCE_DIR}/..")
  set_source_files_properties(tests/scip/test_models.cpp PROPERTIES COMPILE_OPTIONS "-UNDEBUG")
  set_target_properties(marginstv_tests PROPERTIES BUILD_RPATH "${SCIP_RPATH}")
endif()
