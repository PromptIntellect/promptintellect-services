# Makefile

# Default Lambda function name
LAMBDA_FUNCTION_NAME ?= pi_exec_test_fitflex
LAMBDA_EXECUTION_ROLE = pi-lambda-3-16113

# Environment variables
PI_EXECUTION_S3_BUCKET_NAME := promptintellect-product-attachments
PI_INPUTS_FOLDER := execution_inputs/3/16154
PI_INTERNAL_FOLDER := execution_internal/3/16154
PI_OPENAI_CHAT_FUNCTION := open-ai-lambda-function-small-chat
PI_OPENAI_IMAGE_FUNCTION := open-ai-lambda-function-small-image
PI_OPENAI_TEXT_TO_SPEECH_FUNCTION := open-ai-lambda-function-small-text_to_speech
PI_RESULTS_FOLDER := execution_results/3/16154

# Cleanup target to remove old deployment packages
clean:
	rm -f lambda_function.zip

# Package target to create a new deployment package
package: clean
	zip -r lambda_function.zip .

# Get the AWS account ID
AWS_ACCOUNT_ID := $(shell aws sts get-caller-identity --query Account --output text)

# Check if the Lambda function exists
check-function:
	@if aws lambda get-function --function-name $(LAMBDA_FUNCTION_NAME) 2>&1 | grep -q 'ResourceNotFoundException'; then \
		echo "Lambda function does not exist, creating..."; \
		make create-function; \
	else \
		echo "Lambda function exists, updating..."; \
		make update-function; \
	fi

# Create a new Lambda function
create-function:
	aws lambda create-function --function-name $(LAMBDA_FUNCTION_NAME) \
		--runtime nodejs20.x \
		--role arn:aws:iam::$(AWS_ACCOUNT_ID):role/$(LAMBDA_EXECUTION_ROLE) \
		--handler index.handler \
		--zip-file fileb://lambda_function.zip
		--environment Variables="{PI_EXECUTION_S3_BUCKET_NAME=$(PI_EXECUTION_S3_BUCKET_NAME),PI_INPUTS_FOLDER=$(PI_INPUTS_FOLDER),PI_INTERNAL_FOLDER=$(PI_INTERNAL_FOLDER),PI_OPENAI_CHAT_FUNCTION=$(PI_OPENAI_CHAT_FUNCTION),PI_OPENAI_IMAGE_FUNCTION=$(PI_OPENAI_IMAGE_FUNCTION),PI_OPENAI_TEXT_TO_SPEECH_FUNCTION=$(PI_OPENAI_TEXT_TO_SPEECH_FUNCTION),PI_RESULTS_FOLDER=$(PI_RESULTS_FOLDER)}"


# Update the existing Lambda function
update-function:
	aws lambda update-function-code --function-name $(LAMBDA_FUNCTION_NAME) --zip-file fileb://lambda_function.zip
	aws lambda update-function-configuration --function-name $(LAMBDA_FUNCTION_NAME) \
		--environment Variables="{PI_EXECUTION_S3_BUCKET_NAME=$(PI_EXECUTION_S3_BUCKET_NAME),PI_INPUTS_FOLDER=$(PI_INPUTS_FOLDER),PI_INTERNAL_FOLDER=$(PI_INTERNAL_FOLDER),PI_OPENAI_CHAT_FUNCTION=$(PI_OPENAI_CHAT_FUNCTION),PI_OPENAI_IMAGE_FUNCTION=$(PI_OPENAI_IMAGE_FUNCTION),PI_OPENAI_TEXT_TO_SPEECH_FUNCTION=$(PI_OPENAI_TEXT_TO_SPEECH_FUNCTION),PI_RESULTS_FOLDER=$(PI_RESULTS_FOLDER)}"


# Deploy target to check and then deploy the Lambda function
deploy: package check-function

# Default target
all: clean package deploy
