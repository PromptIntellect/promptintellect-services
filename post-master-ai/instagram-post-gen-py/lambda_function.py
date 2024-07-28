import json
import boto3
import os
import requests
import markdown
import re

s3_client = boto3.client('s3')
lambda_client = boto3.client('lambda')

def invoke_openai_lambda(execution_id, user_id, product_id, prompt, service, size, openai_function):
    """
    Invokes the OpenAI Lambda function to generate content.
    """
    openai_payload = {
        "execution_id": execution_id,
        "user_id": user_id,
        "product_id": product_id,
        "service": service,
        "size": size,
        "prompt": prompt
    }

    response = lambda_client.invoke(
        FunctionName=openai_function,
        InvocationType='RequestResponse',
        Payload=json.dumps(openai_payload)
    )

    response_payload = json.load(response['Payload'])
    status_code = response_payload.get('status_code')
    if status_code != 200:
        raise Exception(f"OpenAI Lambda function returned status code {status_code} with body {response_payload.get('body')}")
    
    return response_payload.get('body')

def download_and_upload_to_s3(url, bucket_name, folder_path):
    """
    Downloads an image from a URL and uploads it to an S3 bucket.
    """
    base_url = url.split('?')[0]
    file_name = folder_path + "/" + base_url.split('/')[-1]

    response = requests.get(url, stream=True)
    s3_client.put_object(Body=response.content, Bucket=bucket_name, Key=file_name)

    print(f"File {file_name} uploaded to S3 bucket {bucket_name}")
    return file_name

def decode_unicode(input_str):
    """Decodes Unicode-escaped string."""
    return re.sub(r'\\u([0-9A-Fa-f]{4})', lambda match: chr(int(match.group(1), 16)), input_str)

def generate_html_message(execution_id, user_id, product_id, caption):
    return f"""
        <div style="padding: 20px; background-color: #f0f0f0; border-radius: 5px;">
            <h2>Instagram Post Creation Result</h2>
            <p><strong>Execution ID:</strong> {execution_id}</p>
            <p><strong>User ID:</strong> {user_id}</p>
            <p><strong>Product ID:</strong> {product_id}</p>
            <p><strong>Caption:</strong><br>
                <pre>{markdown.markdown(decode_unicode(caption))}</pre>
            </p>
        </div>
    """

def send_result_to_wordpress(result):
    post_data = json.dumps(result)
    wordpress_url = 'https://promptintellect.com/wp-json/product-extension/v1/lambda-results'
    
    headers = {
        'Content-Type': 'application/json',
        'Content-Length': str(len(post_data))
    }
    
    response = requests.post(wordpress_url, headers=headers, data=post_data)
    if response.status_code != 200:
        raise Exception(f"Unexpected status code: {response.status_code}, {response.text}")

def handler(event, context):
    try:
        # Extract environment variables
        bucket_name = os.environ['PI_EXECUTION_S3_BUCKET_NAME']
        result_folder = os.environ['PI_RESULTS_FOLDER']
        openai_function = os.environ['PI_OPENAI_FUNCTION']
        
        # Extract event data
        execution_id = event['execution_id']
        user_id = event['user_id']
        product_id = event['product_id']
        token = event['token']
        custom_inputs = event['custom_inputs']
        explanation = custom_inputs.get('explanation', '')

        # Generate Instagram post caption
        caption_prompt = f"Create an Instagram post caption based on the following explanation:\n\n{explanation}"
        openai_caption_result = invoke_openai_lambda(execution_id, user_id, product_id, caption_prompt, "chat-gpt-4o", "1x", openai_function)
        caption = openai_caption_result['choices'][0]['message']['content']

        # Generate Instagram post image
        image_prompt = f"Generate an image based on the following explanation:\n\n{explanation}"
        openai_image_result = invoke_openai_lambda(execution_id, user_id, product_id, image_prompt, "image-dall-e-3", "1x", openai_function)
        image_url = openai_image_result["data"][0]["url"]

        # Upload the image to S3
        uploaded_image_key = download_and_upload_to_s3(image_url, bucket_name, f"{result_folder}/{execution_id}")

        # Prepare the result
        html_message = generate_html_message(execution_id, user_id, product_id, caption)

        result = {
            "execution_id": execution_id,
            "user_id": user_id,
            "product_id": product_id,
            "token": token,
            "status": "successful",
            "results": html_message
        }

        # Send the result to the endpoint
        send_result_to_wordpress(result)
        
        return {
            'statusCode': 200,
            'body': json.dumps({'message': 'Task executed successfully'})
        }
    
    except Exception as e:
        error_message = str(e)
        print(f"Error: {error_message}")

        error_result = {
            "execution_id": execution_id,
            "user_id": user_id,
            "product_id": product_id,
            "token": token,
            "status": "failed",
            "results": f"""
                <div style="padding: 20px; color: #ff3333; background-color: #fec4c4; border-radius: 5px;">
                    <p><strong>Error: </strong> {error_message}</p>
                </div>
            """
        }

        send_result_to_wordpress(error_result)

        return {
            'statusCode': 500,
            'body': json.dumps({'message': error_message})
        }
