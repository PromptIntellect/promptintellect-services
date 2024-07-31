# Variables
GOOS=linux
GOARCH=amd64
BINARY_NAME=bootstrap
ZIP_FILE=lambda_function.zip

# Initialize Go modules
init:
	go mod tidy

# Build the Go binary
build:
	GOOS=$(GOOS) GOARCH=$(GOARCH) go build -tags lambda.norpc -o $(BINARY_NAME) main.go

# Create the deployment package (zip)
package: build
	zip $(ZIP_FILE) $(BINARY_NAME)

# Clean up generated files
clean:
	rm -f $(BINARY_NAME) $(ZIP_FILE)

# Default target (initialize, build, and package)
all: clean init package

.PHONY: build package clean all init
