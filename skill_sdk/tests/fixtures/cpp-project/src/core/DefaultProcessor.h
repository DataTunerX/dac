#pragma once

#include "DataProcessor.h"
#include "ProcessorConfig.h"

/**
 * DefaultProcessor is the primary implementation of DataProcessor.
 * goToImplementation should list this class when invoked from DataProcessor.
 */
class DefaultProcessor : public DataProcessor {
public:
    explicit DefaultProcessor();
    explicit DefaultProcessor(const ProcessorConfig& config);

    std::string Process(const std::string& data) override;
    bool Validate(const std::string& data) const override;

    /** ConfigureRetries adjusts the retry count at runtime. */
    void ConfigureRetries(int retries);

    /** GetConfig exposes the current configuration. */
    const ProcessorConfig& GetConfig() const;

private:
    ProcessorConfig config_;
    std::string TransformData(const std::string& data) const;
};
