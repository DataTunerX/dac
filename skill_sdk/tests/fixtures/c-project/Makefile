# C Fixture Project - Makefile
# Builds the C test fixture for clangd LSP testing.

CC = clang
CFLAGS = -std=c17 -Wall -Wextra -I src
LDFLAGS =

SRCS = src/main.c \
       src/core/default_processor.c \
       src/core/handler.c \
       src/core/helper.c \
       src/core/finalize_output.c \
       src/shop/models.c \
       src/shop/cart.c \
       src/shop/percentage_discount.c \
       src/shop/fixed_amount_discount.c \
       src/shop/bogo_discount.c \
       src/shop/stripe_gateway.c \
       src/shop/paypal_gateway.c \
       src/shop/mock_gateway.c \
       src/shop/inmemory_repository.c \
       src/shop/postgres_repository.c \
       src/shop/order_service.c

OBJS = $(SRCS:.c=.o)
TARGET = fixture_app

.PHONY: all clean compile_commands

all: $(TARGET)

$(TARGET): $(OBJS)
	$(CC) $(CFLAGS) -o $@ $^ $(LDFLAGS)

%.o: %.c
	$(CC) $(CFLAGS) -c -o $@ $<

compile_commands:
	@echo '[' > compile_commands.json
	@first=1; \
	for src in $(SRCS); do \
		dir=$$(dirname $$src); \
		if [ $$first -eq 1 ]; then first=0; else echo ',' >> compile_commands.json; fi; \
		echo "  { \"directory\": \"$$(pwd)\", \"command\": \"$(CC) $(CFLAGS) -c $$src -o $${src%.c}.o\", \"file\": \"$$src\" }" >> compile_commands.json; \
	done
	@echo ']' >> compile_commands.json
	@echo "Generated compile_commands.json"

clean:
	rm -f $(OBJS) $(TARGET)
