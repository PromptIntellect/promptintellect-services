# Clean target to remove old deployment packages and build output
clean:
	rm -f bin/lambda_function.zip
	rm -rf bin/Release/net8.0/publish/*

# Restore dependencies from the csproj file
restore:
	dotnet restore src/SmartBrandBlogPost/SmartBrandBlogPost.csproj

# Install additional dependencies listed in dependencies.txt
dependencies:
	@echo "Installing additional dependencies..."
	@cat dependencies.txt | xargs -n 1 dotnet add src/SmartBrandBlogPost package

# Build target to compile the .NET project
build: clean restore dependencies
	dotnet publish src/SmartBrandBlogPost/SmartBrandBlogPost.csproj -c Release -o bin/Release/net8.0/publish

# Package target to create a new deployment package locally
package: build
	cd bin/Release/net8.0/publish && zip -r ../../../lambda_function.zip .

# Help target to display available commands
help:
	@echo "Available commands:"
	@echo "  make clean        - Clean old build files and deployment packages"
	@echo "  make restore      - Restore dependencies"
	@echo "  make dependencies - Install additional dependencies from dependencies.txt"
	@echo "  make build        - Build the .NET project"
	@echo "  make package      - Package the build output into lambda_function.zip"
	@echo ""
	@echo "Prerequisites:"
	@echo "  1. Install .NET SDK: 'brew install --cask dotnet-sdk'"
	@echo "  2. Install AWS CLI: 'brew install awscli'"
	@echo "  3. Initialize the project: 'dotnet new lambda.EmptyFunction -n SmartBrandBlogPost'"
