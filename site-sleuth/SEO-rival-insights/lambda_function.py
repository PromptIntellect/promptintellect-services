import json
import boto3
import os
import requests
import emoji
import markdown
from bs4 import BeautifulSoup, Comment

s3_client = boto3.client('s3')
lambda_client = boto3.client('lambda')

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:98.0) Gecko/20100101 Firefox/98.0",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Cache-Control": "max-age=0",
}

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
        competitor_url = custom_inputs['competitor_url']
        user_website_url = custom_inputs['user_website_url']
        
        # Crawl and extract website content for both the user and competitor websites
        user_data = crawl_website(user_website_url)
        competitor_data = crawl_website(competitor_url)
        
        # Generate a detailed prompt for OpenAI to analyze the competitor
        prompt = generate_competitor_analysis_prompt(user_data, competitor_data, user_website_url, competitor_url)
        
        # Invoke the OpenAI function for competitor SEO analysis
        openai_payload = {
            "execution_id": execution_id,
            "user_id": user_id,
            "product_id": product_id,
            "service": "chat-gpt-4o-mini",
            "size": "11x",
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
            raise Exception(f"OpenAI chat function returned {status_code} as status code with body {str(response_payload.get('body'))}")
        function_result = response_payload.get('body')
        
        if function_result is None:
            raise Exception("No result from OpenAI chat function")
        
        # Save the result to S3
        result_key = f"{result_folder}/{execution_id}/competitor_seo_result.json"
        s3_client.put_object(Bucket=bucket_name, Key=result_key, Body=json.dumps(function_result, indent=4))
        
        # Send the result as HTML to the endpoint
        html_message = generate_html_message(execution_id, user_id, product_id, function_result)
        
        send_result_to_wordpress({
            "execution_id": execution_id,
            "user_id": user_id,
            "product_id": product_id,
            "token": token,
            "status": "successful",
            "results": html_message
        })
        
        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': 'Task executed successfully'
            })
        }
    
    except Exception as e:
        print(f"Error: {str(e)}")

        send_result_to_wordpress({
            "execution_id": execution_id,
            "user_id": user_id,
            "product_id": product_id,
            "token": token,
            "status": "failed",
            "results": f"""
                <div style="padding: 20px; color: #ff3333; background-color: #fec4c4; border-radius: 5px;">
                    <p><strong>Error: </strong> {str(e)}</p>
                </div>
            """
        })

        return {
            'statusCode': 500,
            'body': json.dumps({
                'message': str(e)
            })
        }

def crawl_website(url):
    response = requests.get(url, headers=HEADERS)
    html = response.text

    # Parse HTML using BeautifulSoup
    soup = BeautifulSoup(html, 'html.parser')

    # Extract relevant SEO elements
    title = soup.title.string if soup.title else "No title found"
    description = soup.find("meta", {"name": "description"})['content'] if soup.find("meta", {"name": "description"}) else "No description found"
    keywords = soup.find("meta", {"name": "keywords"})['content'] if soup.find("meta", {"name": "keywords"}) else "No keywords found"
    h1_tags = [h1.get_text() for h1 in soup.find_all('h1')]
    h2_tags = [h2.get_text() for h2 in soup.find_all('h2')]
    h3_tags = [h3.get_text() for h3 in soup.find_all('h3')]
    alt_texts = [img['alt'] for img in soup.find_all('img') if img.has_attr('alt')]
    links = [a['href'] for a in soup.find_all('a') if a.has_attr('href')]
    
    # Removing unnecessary parts of the HTML
    # Remove script, style, and comments
    for script in soup(["script", "style"]):
        script.extract()
    comments = soup.findAll(text=lambda text: isinstance(text, Comment))
    [comment.extract() for comment in comments]

    # Remove unnecessary attributes from tags
    for tag in soup.find_all(True):
        # Only keep certain attributes for <a> tags
        if tag.name == 'a':
            attrs = {key: tag.attrs[key] for key in ['href'] if key in tag.attrs}
            tag.attrs = attrs
        # Remove all attributes for other tags
        else:
            tag.attrs = {}

    # Cleaned HTML content
    cleaned_html = soup.prettify()

    crawled_data = {
        "title": title,
        "description": description,
        "keywords": keywords,
        "h1_tags": h1_tags,
        "h2_tags": h2_tags,
        "h3_tags": h3_tags,
        "alt_texts": alt_texts,
        "links": links,
        "cleaned_html": cleaned_html  # Reduced HTML content for analysis
    }

    return crawled_data

def generate_competitor_analysis_prompt(user_data, competitor_data, user_website_url, competitor_url):
    return f"""
    You are an expert in SEO analysis. I have provided you with the relevant crawled data from two websites: the user's website ({user_website_url}) and a competitor's website ({competitor_url}). 
    Here is the information for the user's website:
    
    - Title: {user_data['title']}
    - Description: {user_data['description']}
    - Keywords: {user_data['keywords']}
    - H1 Tags: {', '.join(user_data['h1_tags'])}
    - H2 Tags: {', '.join(user_data['h2_tags'])}
    - H3 Tags: {', '.join(user_data['h3_tags'])}
    - Alt Texts: {', '.join(user_data['alt_texts'])}
    - Links: {', '.join(user_data['links'])}
    - Cleaned HTML: ``` {user_data['cleaned_html']} ```
    
    And here is the information for the competitor's website:
    
    - Title: {competitor_data['title']}
    - Description: {competitor_data['description']}
    - Keywords: {competitor_data['keywords']}
    - H1 Tags: {', '.join(competitor_data['h1_tags'])}
    - H2 Tags: {', '.join(competitor_data['h2_tags'])}
    - H3 Tags: {', '.join(competitor_data['h3_tags'])}
    - Alt Texts: {', '.join(competitor_data['alt_texts'])}
    - Links: {', '.join(competitor_data['links'])}
    - Cleaned HTML: ``` {competitor_data['cleaned_html']} ```
    
    Please perform a detailed SEO competitor analysis, focusing on the following aspects:
    
    1. Comparative SEO performance of the user's website and the competitor's website.
    2. Strengths and weaknesses of both websites in terms of SEO.
    3. Opportunities for the user to improve and outperform the competitor in SEO.
    4. Specific recommendations for improving the user's website SEO to gain an edge over the competitor.
    
    Provide your analysis in a structured format with actionable insights.
    """

def generate_html_message(execution_id, user_id, product_id, response):
    response_text = response['choices'][0]['message']['content']
    emojized_text = emoji.emojize(response_text)
    html_str = markdown.markdown(emojized_text)
    return f"""
        <div style="padding: 20px; background-color: #f0f0f0; border-radius: 5px;">
            <h2>SEO Competitor Analysis Result</h2>
            <p><strong>Execution ID:</strong> {execution_id}</p>
            <p><strong>User ID:</strong> {user_id}</p>
            <p><strong>Product ID:</strong> {product_id}</p>
            <p><strong>Analysis Results:</strong><br>
                <div>{html_str}</div>
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

    response = requests.post(wordpress_url, data=post_data, headers=headers)
    
    if response.status_code != 200:
        raise Exception(f"Failed to send result to WordPress. Status code: {response.status_code}, Response: {response.text}")
    
    return response.text
