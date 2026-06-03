#include "Handler.h"
#include "Helper.h"

#include <iostream>
#include <stdexcept>

Handler::Handler(std::shared_ptr<DataProcessor> processor)
    : processor_(std::move(processor)) {}

std::string Handler::ProcessRequest(const std::string& payload) {
    std::cout << "Processing request: " << payload << std::endl;

    auto helper = NewHelper(processor_);
    auto result = helper.HandleRequest(payload);
    return result;
}

bool Handler::HealthCheck() const {
    return processor_ != nullptr;
}
