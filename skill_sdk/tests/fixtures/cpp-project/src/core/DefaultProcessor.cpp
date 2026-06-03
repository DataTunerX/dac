#include "DefaultProcessor.h"

#include <stdexcept>

DefaultProcessor::DefaultProcessor() : config_() {}

DefaultProcessor::DefaultProcessor(const ProcessorConfig& config) : config_(config) {}

std::string DefaultProcessor::Process(const std::string& data) {
    if (!Validate(data)) {
        throw std::runtime_error("invalid data: " + data);
    }
    return TransformData(data);
}

bool DefaultProcessor::Validate(const std::string& data) const {
    return !data.empty() && data.size() < 1024;
}

std::string DefaultProcessor::TransformData(const std::string& data) const {
    return "processed: " + data;
}

void DefaultProcessor::ConfigureRetries(int retries) {
    config_.retries = retries;
}

const ProcessorConfig& DefaultProcessor::GetConfig() const {
    return config_;
}
