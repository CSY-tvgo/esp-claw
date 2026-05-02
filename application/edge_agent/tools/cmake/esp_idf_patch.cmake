set(EDGE_AGENT_PROJECT_LOG_PREFIX "[edge_agent]")
set(EDGE_AGENT_ESP_IDF_PATCH "${CMAKE_SOURCE_DIR}/tools/esp-idf.patch")

if(NOT DEFINED ENV{IDF_PATH} OR "$ENV{IDF_PATH}" STREQUAL "")
    message(FATAL_ERROR "${EDGE_AGENT_PROJECT_LOG_PREFIX} IDF_PATH environment variable is not set")
endif()

find_program(GIT_EXECUTABLE git REQUIRED)

if(EXISTS "${EDGE_AGENT_ESP_IDF_PATCH}")
    # First do a dry-run to check if the patch can be applied cleanly
    execute_process(
        COMMAND ${GIT_EXECUTABLE} apply --check --ignore-whitespace "${EDGE_AGENT_ESP_IDF_PATCH}"
        WORKING_DIRECTORY "$ENV{IDF_PATH}"
        RESULT_VARIABLE EDGE_AGENT_PATCH_CHECK_RESULT
        OUTPUT_QUIET
        ERROR_QUIET
    )

    if(EDGE_AGENT_PATCH_CHECK_RESULT EQUAL 0)
        # Patch applies cleanly — apply it
        execute_process(
            COMMAND ${GIT_EXECUTABLE} apply --ignore-whitespace "${EDGE_AGENT_ESP_IDF_PATCH}"
            WORKING_DIRECTORY "$ENV{IDF_PATH}"
            RESULT_VARIABLE EDGE_AGENT_PATCH_APPLY_RESULT
            OUTPUT_VARIABLE EDGE_AGENT_PATCH_APPLY_STDOUT
            ERROR_VARIABLE EDGE_AGENT_PATCH_APPLY_STDERR
        )

        if(NOT EDGE_AGENT_PATCH_APPLY_RESULT EQUAL 0)
            message(FATAL_ERROR
                "${EDGE_AGENT_PROJECT_LOG_PREFIX} Failed to apply ESP-IDF patch: ${EDGE_AGENT_ESP_IDF_PATCH}\n"
                "stdout:\n${EDGE_AGENT_PATCH_APPLY_STDOUT}\n"
                "stderr:\n${EDGE_AGENT_PATCH_APPLY_STDERR}")
        endif()

        message(STATUS "${EDGE_AGENT_PROJECT_LOG_PREFIX} Applied ESP-IDF patch: ${EDGE_AGENT_ESP_IDF_PATCH}")
    else()
        # Patch does not apply cleanly; check if it was already applied
        execute_process(
            COMMAND ${GIT_EXECUTABLE} apply --reverse --check --ignore-whitespace "${EDGE_AGENT_ESP_IDF_PATCH}"
            WORKING_DIRECTORY "$ENV{IDF_PATH}"
            RESULT_VARIABLE EDGE_AGENT_PATCH_ALREADY_APPLIED
            OUTPUT_QUIET
            ERROR_QUIET
        )

        if(EDGE_AGENT_PATCH_ALREADY_APPLIED EQUAL 0)
            message(STATUS "${EDGE_AGENT_PROJECT_LOG_PREFIX} ESP-IDF patch already applied: ${EDGE_AGENT_ESP_IDF_PATCH}")
        else()
            # Neither forward nor reverse applies — the fixes are likely already
            # merged upstream in this ESP-IDF version.  Emit a warning and continue.
            message(WARNING
                "${EDGE_AGENT_PROJECT_LOG_PREFIX} ESP-IDF patch is not applicable to this ESP-IDF version "
                "(it may already be fixed upstream): ${EDGE_AGENT_ESP_IDF_PATCH}")
        endif()
    endif()
else()
    message(FATAL_ERROR "${EDGE_AGENT_PROJECT_LOG_PREFIX} ESP-IDF patch file not found: ${EDGE_AGENT_ESP_IDF_PATCH}")
endif()
