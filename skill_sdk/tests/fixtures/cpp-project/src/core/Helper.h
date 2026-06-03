#pragma once

#include "DataProcessor.h"

#include <memory>
#include <string>

/**
 * Helper bridges the processor with external systems.
 * outgoingCalls on HandleRequest should list: processor.Validate, processor.Process,
 * ConfigureRetries, FinalizeOutput.
 * incomingCalls on ProcessRequest (Handler) should show HandleRequest as caller.
 */
class Helper {
public:
    explicit Helper(std::shared_ptr<DataProcessor> processor);

    /**
     * HandleRequest processes a request through the pipeline.
     * This is the call-hierarchy centrepiece for the core module.
     * outgoingCalls: Validate, Process, FinalizeOutput.
     * incomingCalls: ProcessRequest (Handler.cpp), demoCoreRun (main.cpp).
     */
    std::string HandleRequest(const std::string& input);

    /** FinalizeOutput applies post-processing to the result. */
    static std::string FinalizeOutput(const std::string& data);

private:
    std::shared_ptr<DataProcessor> processor_;
};

/**
 * NewHelper factory function — defined in Helper.cpp.
 * goToDefinition from Handler.cpp should resolve to Helper.cpp.
 */
std::unique_ptr<Helper> NewHelper(std::shared_ptr<DataProcessor> proc);
