# Variables
LAMBDA_FUNCTION_NAME := lambda_function.rb
ZIP_FILE := lambda_function.zip
DEPLOY_DIR := deploy
BUNDLE_DIR := $(DEPLOY_DIR)/bundle

# Targets
.PHONY: all clean prepare install package

# Default target
all: clean prepare install package

# Clean up previous build artifacts
clean:
	rm -rf $(DEPLOY_DIR)
	rm -f $(ZIP_FILE)

# Prepare deployment directory
prepare:
	mkdir -p $(BUNDLE_DIR)
	cp $(LAMBDA_FUNCTION_NAME) $(BUNDLE_DIR)/
	cp -R vendor/bundle $(BUNDLE_DIR)/vendor

# Install dependencies
install:
	bundle install --path vendor/bundle

# Package the deployment directory into a zip file
package:
	cd $(BUNDLE_DIR) && zip -r ../../$(ZIP_FILE) .

# Clean and then build the deployment package
build: clean all
