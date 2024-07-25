const AWS = require('aws-sdk');
const https = require('https');
const axios = require('axios');
const cheerio = require('cheerio');
const s3 = new AWS.S3();
const lambda = new AWS.Lambda();

exports.handler = async (event) => {
  const {
    execution_id,
    user_id,
    product_id,
    token,
    custom_inputs: { keywords }
  } = event;

  const bucketName = process.env.PI_EXECUTION_S3_BUCKET_NAME;
  const resultFolder = process.env.PI_RESULTS_FOLDER;
  const executionParams = { execution_id, product_id, user_id };

  try {
    // Generate a search query using ChatGPT
    const searchQuery = await generateSearchQuery(keywords, executionParams);

    // Search for articles using the generated query
    const articles = await fetchArticlesFromGoogle(searchQuery);

    // Generate a blog post using the retrieved articles
    const blogPost = await generateBlogPost(articles, keywords, executionParams);

    // Save the blog post to S3 as a .txt file
    const txtKey = `${resultFolder}/${execution_id}/blog_post.txt`;

    await s3.putObject({
      Bucket: bucketName,
      Key: txtKey,
      Body: blogPost,
      ContentType: 'text/plain'
    }).promise();

    // Send results to WordPress
    await sendResultToWordPress({
      execution_id,
      user_id,
      product_id,
      token,
      status: 'successful',
      results: `<div>Your blog post is ready! The post is created in markdown format to be compatible with most blog platforms.</div>
      <div>AutoBlog Generator at your service.</div>
      `
    });

    return {
      statusCode: 200,
      body: JSON.stringify({
        message: 'Blog post generated successfully',
        txtUrl: `https://${bucketName}.s3.amazonaws.com/${txtKey}`
      })
    };
  } catch (error) {
    console.error(error);

    await sendResultToWordPress({
      execution_id,
      user_id,
      product_id,
      token,
      status: 'failed',
      results: `<div style="padding: 20px; color: #ff3333; background-color: #fec4c4; border-radius: 5px;">
                  <p><strong>Error: </strong> ${error.message}</p>
                </div>`
    });

    return {
      statusCode: 500,
      body: JSON.stringify({
        message: 'Failed to generate blog post',
        error: error.message
      })
    };
  }
};

async function generateSearchQuery(keywords, { execution_id, product_id, user_id }) {
  const prompt = `
    Generate a detailed and precise search query based on the following keywords: ${keywords}.
    The query should be optimized to find relevant and high-quality articles. Your answer should be just the search query based on the keywords.
    I want just the search query without anything after or before that, like "Here is the answer....". I literally want to use your answer like this:
    https://www.google.com/search?q={encodeURIComponent(your-generated-query)}
  `;

  const response = await invokeOpenAiLambda(prompt, execution_id, product_id, user_id, 'chat-gpt-4o', '1x');
  console.log(`generateSearchQuery response: ${response}`);
  return response.trim();
}

async function fetchArticlesFromGoogle(query) {
  const searchUrl = `https://www.google.com/?q=${encodeURIComponent(query)}`;
  console.log(`fetchArticlesFromGoogle searchUrl: ${searchUrl}`);
  const response = await axios.get(searchUrl);
  const $ = cheerio.load(response.data);
  const articles = [];

  $('a[href^="/url"]').each((index, element) => {
    if (index < 3) {
      const url = $(element).attr('href');
      const actualUrl = url.match(/url\?q=([^&]+)/);
      if (actualUrl && actualUrl[1]) {
        articles.push(actualUrl[1]);
      }
    }
  });

  return articles;
}

async function generateBlogPost(articles, keywords, { execution_id, product_id, user_id }) {
  let articleContents = '';

  for (const url of articles) {
    try {
      const response = await axios.get(url);
      const $ = cheerio.load(response.data);
      articleContents += $('body').text();
    } catch (error) {
      console.error(`Failed to fetch content from ${url}: ${error.message}`);
    }
  }

  const prompt = `
    Generate a blog post in Markdown format based on the following articles:
    ${articleContents}
    
    Keywords: ${keywords}

    The blog post should be informative, engaging, and relevant to the keywords.
    Finish the post with the reference to articles ${JSON.stringify(articles)};
  `;

  const openaiResult = await invokeOpenAiLambda(prompt, execution_id, product_id, user_id, 'chat-gpt-4o', '2x');

  return openaiResult;
}

async function invokeOpenAiLambda(prompt, execution_id, product_id, user_id, service, size) {
  const payload = {
    user_id,
    product_id,
    execution_id,
    prompt,
    service,
    size
  };

  const response = await lambda.invoke({
    FunctionName: process.env.PI_OPENAI_FUNCTION,
    InvocationType: 'RequestResponse',
    Payload: JSON.stringify(payload),
  }).promise();

  const responsePayload = JSON.parse(response.Payload);
  if (responsePayload.status_code !== 200) {
    throw new Error(`OpenAI Lambda function returned status code ${responsePayload.status_code}. 
    Error: ${JSON.stringify(responsePayload.body, null, 2)}`);
  }

  return responsePayload.body.choices[0].message.content;
}

function sendResultToWordPress(result) {
  const postData = JSON.stringify(result);
  const options = {
    hostname: 'promptintellect.com',
    port: 443,
    path: '/wp-json/product-extension/v1/lambda-results',
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Content-Length': Buffer.byteLength(postData)
    }
  };

  return new Promise((resolve, reject) => {
    const req = https.request(options, (res) => {
      let data = '';

      res.on('data', (chunk) => {
        data += chunk;
      });

      res.on('end', () => {
        if (res.statusCode === 200) {
          resolve(data);
        } else {
          reject(new Error(`Unexpected status code: ${res.statusCode}`));
        }
      });
    });

    req.on('error', (error) => {
      reject(error);
    });

    req.write(postData);
    req.end();
  });
}
