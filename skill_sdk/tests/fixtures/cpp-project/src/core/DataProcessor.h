#pragma once

#include <string>

/**
 * DataProcessor defines the contract for processing data.
 * goToDefinition on DataProcessor should resolve to this header.
 * findReferences on DataProcessor should find all usages across core/ and shop/.
 * goToImplementation on DataProcessor should resolve to DefaultProcessor.
 */
class DataProcessor {
public:
    virtual ~DataProcessor() = default;

    /**
     * Process applies the data processing pipeline.
     * hover on Process should show documentation comment.
     */
    virtual std::string Process(const std::string& data) = 0;

    /**
     * Validate checks whether the provided data is valid.
     */
    virtual bool Validate(const std::string& data) const = 0;
};
