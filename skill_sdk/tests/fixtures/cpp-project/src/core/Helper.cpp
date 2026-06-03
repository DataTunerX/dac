#include "Helper.h"

#include <stdexcept>

Helper::Helper(std::shared_ptr<DataProcessor> processor)
    : processor_(std::move(processor)) {}

std::string Helper::HandleRequest(const std::string& input) {
    bool validated = processor_->Validate(input);
    if (!validated) {
        throw std::runtime_error("validation failed");
    }
    std::string result = processor_->Process(input);
    return FinalizeOutput(result);
}

std::string Helper::FinalizeOutput(const std::string& data) {
    return "[final] " + data + " [ok]";
}

std::unique_ptr<Helper> NewHelper(std::shared_ptr<DataProcessor> proc) {
    return std::make_unique<Helper>(std::move(proc));
}
