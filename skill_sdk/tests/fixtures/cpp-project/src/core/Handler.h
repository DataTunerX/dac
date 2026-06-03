#pragma once

#include "DataProcessor.h"

#include <memory>
#include <string>

/**
 * Handler processes incoming API requests.
 * crossed-file: NewHelper is called from here but defined in Helper.h/cpp.
 */
class Handler {
public:
    explicit Handler(std::shared_ptr<DataProcessor> processor);

    /**
     * ProcessRequest handles an API request end-to-end.
     * Calls NewHelper then helper.HandleRequest.
     */
    std::string ProcessRequest(const std::string& payload);

    /** HealthCheck reports the handler health status. */
    bool HealthCheck() const;

private:
    std::shared_ptr<DataProcessor> processor_;
};
