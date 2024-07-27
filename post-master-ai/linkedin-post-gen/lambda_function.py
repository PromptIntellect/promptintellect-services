import json
import boto3
import os
import requests
import feedparser
import markdown
import re

lambda_client = boto3.client('lambda')
s3_client = boto3.client('s3')

RSS_FEED_URL = 'https://rss.nytimes.com/services/xml/rss/nyt/World.xml'

def get_latest_news(rss_feed_url):
    """
    Fetches the latest news articles from the RSS feed.
    """
    feed = feedparser.parse(rss_feed_url)
    return feed.entries

def filter_news(articles, keywords):
    """
    Filters news articles based on user-required keywords.
    """
    filtered_articles = []
    for article in articles:
        for keyword in keywords:
            if keyword.lower() in article.title.lower() or keyword.lower() in article.description.lower():
                filtered_articles.append(article)
                break
    return filtered_articles

def invoke_openai_lambda(execution_id, user_id, product_id, prompt, openai_function):
    """
    Invokes the OpenAI Lambda function to generate a LinkedIn post.
    """
    openai_payload = {
        "execution_id": execution_id,
        "user_id": user_id,
        "product_id": product_id,
        "service": "chat-gpt-4o",
        "size": "1x",
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

def decode_unicode(input_str):
    """Decodes Unicode-escaped string."""
    return re.sub(r'\\u([0-9A-Fa-f]{4})', lambda match: chr(int(match.group(1), 16)), input_str)

def generate_html_message(execution_id, user_id, product_id, result):
    markdown_string = result['choices'][0]['message']['content']
    
    # Decode the Unicode string
    decoded_string = decode_unicode(markdown_string)
    
    # Convert the decoded Markdown string to HTML
    html_content = markdown.markdown(decoded_string)
    
    # formatted_response = json.dumps(result, indent=4)
    
    return f"""
        <div style="padding: 20px; background-color: #f0f0f0; border-radius: 5px;">
            <h2>Task Execution Result</h2>
            <p><strong>Execution ID:</strong> {execution_id}</p>
            <p><strong>User ID:</strong> {user_id}</p>
            <p><strong>Product ID:</strong> {product_id}</p>
            <strong>Response:</strong><br>
            <div>
                {html_content}
            </div>
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
        keywords = [keyword.strip() for keyword in custom_inputs.get('keywords', '').replace('-', ',').split(',')]
        
        # Fetch and filter news articles
        feed_url = RSS_FEED_URL
        articles = get_latest_news(feed_url)
        filtered_articles = filter_news(articles, keywords)
        
        if not filtered_articles:
            raise Exception("No articles found matching the keywords")

        # Generate a LinkedIn post prompt
        news_summary = "\n\n".join([f"Title: {article.title}\nLink: {article.link}" for article in filtered_articles])
        prompt = f"Write a LinkedIn post based on the following news articles:\n\n{news_summary}"

        # Invoke OpenAI Lambda function
        openai_result = invoke_openai_lambda(execution_id, user_id, product_id, prompt, openai_function)
        
        # Save the result to S3
        result_key = f"{result_folder}/{execution_id}/result.json"
        s3_client.put_object(Bucket=bucket_name, Key=result_key, Body=json.dumps(openai_result, indent=4))

        # Prepare the result
        html_message = generate_html_message(execution_id, user_id, product_id, openai_result)

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
