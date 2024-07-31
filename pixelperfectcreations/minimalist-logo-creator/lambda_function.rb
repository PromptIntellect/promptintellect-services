require 'aws-sdk-s3'
require 'aws-sdk-lambda'
require 'json'
require 'net/http'
require 'uri'

def lambda_handler(event:, context:)
  execution_id = event['execution_id']
  user_id = event['user_id']
  product_id = event['product_id']
  token = event['token']
  custom_inputs = event['custom_inputs']
  business_name = custom_inputs['business_name']
  industry = custom_inputs['industry']
  style_preference = custom_inputs['style_preference']

  bucket_name = ENV['PI_EXECUTION_S3_BUCKET_NAME']
  result_folder = ENV['PI_RESULTS_FOLDER']

  begin
    prompt = generate_prompt(business_name, industry, style_preference)
    logo_data = invoke_openai_lambda(prompt, execution_id, product_id, user_id, 'image-dall-e-3', '1x')
    
    # Log the logo data
    puts "Logo Data: #{logo_data.inspect}"
    
    logo_url = logo_data['data'][0]['url']

    puts "logo_url: #{logo_url}"
    
    # Download the image
    image = download_image(logo_url)

    # Define the S3 key for the uploaded image
    image_key = "#{result_folder}/#{execution_id}/logo.png"
    puts "image_key: #{image_key}"

    # Upload the image to S3
    s3 = Aws::S3::Client.new
    s3.put_object(bucket: bucket_name, key: image_key, body: image, content_type: 'image/png')

    html_message = generate_html_message(logo_url)

    send_result_to_wordpress(
      execution_id: execution_id,
      user_id: user_id,
      product_id: product_id,
      token: token,
      status: 'successful',
      results: html_message
    )

    { statusCode: 200, body: JSON.generate(message: 'Logo generated successfully', imageUrl: "https://#{bucket_name}.s3.amazonaws.com/#{image_key}") }
  rescue => e
    puts e.message

    send_result_to_wordpress(
      execution_id: execution_id,
      user_id: user_id,
      product_id: product_id,
      token: token,
      status: 'failed',
      results: "<div style='padding: 20px; color: #ff3333; background-color: #fec4c4; border-radius: 5px;'><p><strong>Error: </strong> #{e.message}</p></div>"
    )

    { statusCode: 500, body: JSON.generate(message: 'Failed to generate logo', error: e.message) }
  end
end

def generate_prompt(business_name, industry, style_preference)
  "Create a logo for a business named #{business_name} in the #{industry} industry. The preferred style is #{style_preference}."
end

def invoke_openai_lambda(prompt, execution_id, product_id, user_id, service, size)
  lambda_client = Aws::Lambda::Client.new
  payload = {
    user_id: user_id,
    product_id: product_id,
    execution_id: execution_id,
    prompt: prompt,
    service: service,
    size: size
  }.to_json

  response = lambda_client.invoke({
    function_name: ENV['PI_OPENAI_FUNCTION'],
    invocation_type: 'RequestResponse',
    payload: payload
  })
  
  response_payload = JSON.parse(response.payload.string)
  raise "OpenAI Lambda function returned status code #{response_payload['status_code']}" unless response_payload['status_code'] == 200

  response_payload['body']
end

def download_image(url)
  uri = URI.parse(url)
  response = Net::HTTP.get_response(uri)
  raise "Failed to download image from #{url}" unless response.is_a?(Net::HTTPSuccess)
  response.body
end

def generate_html_message(logo_url)
  "<div style='padding: 20px; background-color: #f0f0f0; border-radius: 5px;'><h2>Your logo is ready!</h2><img src='#{logo_url}' alt='Generated Logo'><h3>Download your logo</h3><p>Your new logo is ready for use. Download the PDF version for high-quality print and digital use.</p></div>"
end

def send_result_to_wordpress(result)
  uri = URI.parse('https://promptintellect.com/wp-json/product-extension/v1/lambda-results')
  http = Net::HTTP.new(uri.host, uri.port)
  http.use_ssl = true

  request = Net::HTTP::Post.new(uri.path, { 'Content-Type' => 'application/json' })
  request.body = result.to_json

  response = http.request(request)
  raise "Unexpected status code: #{response.code}" unless response.code == '200'

  response.body
end
