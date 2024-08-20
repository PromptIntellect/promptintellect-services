import json
import boto3
import os
import requests
import emoji
import markdown
from bs4 import BeautifulSoup, Comment  # Import Comment
from urllib.request import urlopen

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
        website_url = custom_inputs['website_url']
        
        # Crawl and extract website content
        crawled_data = crawl_website(website_url)
        
        # Generate a detailed prompt for OpenAI
        prompt = generate_seo_analysis_prompt(crawled_data, website_url)
        
        # Invoke the OpenAI function for SEO analysis
        openai_payload = {
            "execution_id": execution_id,
            "user_id": user_id,
            "product_id": product_id,
            "service": "chat-gpt-4o-mini",
            "size": "9x",
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
            raise Exception(f"OpenAI chat function returns {status_code} as status code with body {str(response_payload.get('body'))}")
        function_result = response_payload.get('body')
        
        if function_result is None:
            raise Exception("No result from OpenAI chat function")
        
        # Save the result to S3
        result_key = f"{result_folder}/{execution_id}/seo_result.json"
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

def generate_seo_analysis_prompt(crawled_data, website_url):
    return f"""
    You are an expert in SEO analysis. I have provided you with the relevant crawled data from the website: {website_url}. 
    Here is the information:
    
    - Title: {crawled_data['title']}
    - Description: {crawled_data['description']}
    - Keywords: {crawled_data['keywords']}
    - H1 Tags: {', '.join(crawled_data['h1_tags'])}
    - H2 Tags: {', '.join(crawled_data['h2_tags'])}
    - H3 Tags: {', '.join(crawled_data['h3_tags'])}
    - Alt Texts: {', '.join(crawled_data['alt_texts'])}
    - Links: {', '.join(crawled_data['links'])}
    
    Here is the cleaned HTML content of the webpage (unnecessary tags and scripts removed):
    {crawled_data['cleaned_html']}
    
    Please analyze this website in terms of SEO and provide detailed insights and recommendations. Your analysis should include, but not be limited to, the following:
    
    1. Overall SEO performance of the website.
    2. Issues with meta tags, titles, and descriptions.
    3. Use of headings (H1, H2, H3, etc.) and their effectiveness.
    4. Keyword optimization and suggestions for improvement.
    5. Use of alt texts for images and suggestions for improvement.
    6. Analysis of internal and external links.
    7. Any missing critical SEO elements.
    8. Recommendations for improving the website's SEO.
    
    Provide your analysis in a structured format with actionable insights.
    """

def generate_html_message(execution_id, user_id, product_id, response):
    response_text = response['choices'][0]['message']['content']
    emojized_text = emoji.emojize(response_text)
    html_str = markdown.markdown(emojized_text)
    return f"""
        <div style="padding: 20px; background-color: #f0f0f0; border-radius: 5px;">
            <h2>SEO Analysis Result</h2>
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
    
    response = requests.post(wordpress_url, headers=headers, data=post_data)
    
    if response.status_code != 200:
        raise Exception(f"Unexpected status code: {response.status_code}, {response.text}")
