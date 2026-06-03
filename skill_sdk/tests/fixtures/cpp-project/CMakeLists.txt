cmake_minimum_required(VERSION 3.16)
project(fixture LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

# Core library (interface + impl)
add_library(fixture_core STATIC
    src/core/DataProcessor.h
    src/core/DefaultProcessor.h
    src/core/DefaultProcessor.cpp
    src/core/ProcessorConfig.h
    src/core/Handler.h
    src/core/Handler.cpp
    src/core/Helper.h
    src/core/Helper.cpp
)

target_include_directories(fixture_core PUBLIC src)

# Shop library (e-commerce subpackage — interface hierarchy + call chain)
add_library(fixture_shop STATIC
    src/shop/models.h
    src/shop/cart.h
    src/shop/cart.cpp
    src/shop/DiscountStrategy.h
    src/shop/PercentageDiscount.h
    src/shop/PercentageDiscount.cpp
    src/shop/FixedAmountDiscount.h
    src/shop/FixedAmountDiscount.cpp
    src/shop/BogoDiscount.h
    src/shop/BogoDiscount.cpp
    src/shop/Repository.h
    src/shop/InMemoryRepository.h
    src/shop/InMemoryRepository.cpp
    src/shop/PostgresRepository.h
    src/shop/PostgresRepository.cpp
    src/shop/PaymentGateway.h
    src/shop/PaymentResult.h
    src/shop/StripeGateway.h
    src/shop/StripeGateway.cpp
    src/shop/PayPalGateway.h
    src/shop/PayPalGateway.cpp
    src/shop/MockGateway.h
    src/shop/MockGateway.cpp
    src/shop/OrderService.h
    src/shop/OrderService.cpp
)

target_include_directories(fixture_shop PUBLIC src)
target_link_libraries(fixture_shop PUBLIC fixture_core)

# Main executable
add_executable(fixture_app src/main.cpp)
target_link_libraries(fixture_app fixture_core fixture_shop)
