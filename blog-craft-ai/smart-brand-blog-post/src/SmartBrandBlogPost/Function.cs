using Amazon.Lambda.Core;
using Amazon.Lambda.Model;
using Amazon.S3;
using Amazon.S3.Model;
using Amazon.Lambda;
using System;
using System.Net.Http;
using System.Text;
using System.Text.Json;
using SystemJsonSerializer = System.Text.Json.JsonSerializer;
using System.Text.Json.Serialization;
using System.Threading.Tasks;
using Newtonsoft.Json;
using HtmlAgilityPack;
using System.Text.RegularExpressions;

// Assembly attribute to enable the Lambda function's JSON input to be converted into a .NET class.
[assembly: LambdaSerializer(typeof(Amazon.Lambda.Serialization.SystemTextJson.DefaultLambdaJsonSerializer))]

namespace SmartBrandBlogPost
{
    public class Function
    {
        private static readonly HttpClient HttpClient = new HttpClient();
        private readonly IAmazonS3 _s3Client = new AmazonS3Client();
        private readonly IAmazonLambda _lambdaClient = new AmazonLambdaClient();
        private readonly string _openAiFunctionName = System.Environment.GetEnvironmentVariable("PI_OPENAI_FUNCTION");

        public async Task<LambdaResponse> Handler(LambdaInput? input, ILambdaContext context)
        {
            // Log the input
            context.Logger.LogLine("Received input: " + SystemJsonSerializer.Serialize(input));

            if (input == null)
            {
                return new LambdaResponse
                {
                    StatusCode = 400,
                    Body = "Request body cannot be null or empty"
                };
            }

            var (executionId, userId, productId, token) = (input.ExecutionId, input.UserId, input.ProductId, input.Token);

            // Check for null or default values
            if (input is null ||
                input.ExecutionId == "" ||
                input.UserId == 0 ||
                input.ProductId == 0 ||
                input.Token == "")
            {
                var errorResponse = new LambdaResponse
                {
                    StatusCode = 400, // Bad Request
                    Body = SystemJsonSerializer.Serialize(new { Message = "Invalid input: one or more required fields are missing." })
                };
                return errorResponse;
            }

            string businessName = input.CustomInputs.BusinessName;
            string websiteUrl = input.CustomInputs.WebsiteUrl;
            string target = input.CustomInputs.Target;

            var bucketName = System.Environment.GetEnvironmentVariable("PI_EXECUTION_S3_BUCKET_NAME");
            var resultFolder = System.Environment.GetEnvironmentVariable("PI_RESULTS_FOLDER");

            try
            {
                // Crawl the website for content and internal links
                var websiteContent = await CrawlWebsite(websiteUrl, 1000);
                // Log the composed string
                context.Logger.LogLine("WebsiteContent: " + websiteContent);

                // Generate a blog post using the website content
                var blogPost = await GenerateBlogPost(websiteContent, target, executionId, productId, userId);

                // Save the blog post to S3 as a .txt file
                var txtKey = $"{resultFolder}/{executionId}/blog_post.txt";


                await _s3Client.PutObjectAsync(new PutObjectRequest
                {
                    BucketName = bucketName,
                    Key = txtKey,
                    ContentBody = blogPost,
                    ContentType = "text/plain"
                });

                context.Logger.LogLine("created the file: " + txtKey);
                // Send results to WordPress
                await SendResultToWordPress(new ResultToWordPress
                {
                    ExecutionId = executionId,
                    UserId = userId,
                    ProductId = productId,
                    Token = token,
                    Status = "successful",
                    Results = "<div>Your blog post is ready! The post is created in markdown format to be compatible with most blog platforms.</div><div>Smart Brand Blog Post at your service.</div>"
                });

                return new LambdaResponse
                {
                    StatusCode = 200,
                    Body = SystemJsonSerializer.Serialize(new
                    {
                        message = "Blog post generated successfully"
                    })
                };
            }
            catch (Exception ex)
            {
                context.Logger.LogLine($"Error: {ex.Message}");

                await SendResultToWordPress(new ResultToWordPress
                {
                    ExecutionId = executionId,
                    UserId = userId,
                    ProductId = productId,
                    Token = token,
                    Status = "failed",
                    Results = $"<div style=\"padding: 20px; color: #ff3333; background-color: #fec4c4; border-radius: 5px;\"><p><strong>Error: </strong> {ex.Message}</p></div>"
                });

                return new LambdaResponse
                {
                    StatusCode = 500,
                    Body = SystemJsonSerializer.Serialize(new
                    {
                        message = "Failed to generate blog post",
                        error = ex.Message
                    })
                };
            }
        }

        private async Task<string> CrawlWebsite(string url, int maxLength)
        {
            // Fetch the HTML content from the URL
            var html = await HttpClient.GetStringAsync(url);

            // Load the HTML into the HtmlDocument
            HtmlDocument doc = new HtmlDocument();
            doc.LoadHtml(html);

            // Initialize a StringBuilder to gather extracted content
            StringBuilder extractedContent = new StringBuilder();

            // Extract information from the navbar, header, and footer
            foreach (var xpath in new[] { "//nav", "//header", "//footer" })
            {
                var elements = doc.DocumentNode.SelectNodes(xpath);
                if (elements != null)
                {
                    foreach (var element in elements)
                    {
                        string cleanedText = Regex.Replace(element.InnerText, @"\s+", " ").Trim();
                        extractedContent.AppendLine(cleanedText);
                    }
                }
            }

            // Attempt to extract contact information
            var contactDetails = doc.DocumentNode.SelectNodes("//*[contains(., 'contact') or contains(., 'Contact') or contains(., 'CONTACT')]");
            if (contactDetails != null)
            {
                foreach (var detail in contactDetails)
                {
                    if (detail.InnerText.Contains("phone", StringComparison.OrdinalIgnoreCase) ||
                        detail.InnerText.Contains("email", StringComparison.OrdinalIgnoreCase) ||
                        detail.InnerText.Contains("address", StringComparison.OrdinalIgnoreCase))
                    {
                        string cleanedText = Regex.Replace(detail.InnerText, @"\s+", " ").Trim();
                        extractedContent.AppendLine(cleanedText);
                    }
                }
            }

            // Remove duplicate whitespace and ensure the result does not exceed the maximum length
            string result = Regex.Replace(extractedContent.ToString(), @"\s+", " ");
            return result.Length > maxLength ? result.Substring(0, maxLength) : result;
        }

        private async Task<string> GenerateBlogPost(string crawledContent, string target, string executionId, int productId, int userId)
        {
            var prompt = $"Generate a blog post in Markdown format based on the content from the website: {crawledContent}. Target to promote or focus on in the post: {target}.";
            return await InvokeOpenAiLambda(prompt, executionId, productId, userId, "chat-gpt-4o", "2x");
        }

        private async Task<string> InvokeOpenAiLambda(string prompt, string executionId, int productId, int userId, string service, string size)
        {
            var payload = new
            {
                user_id = userId,
                product_id = productId,
                execution_id = executionId,
                prompt,
                service,
                size
            };

            Console.WriteLine($"payload: {System.Text.Json.JsonSerializer.Serialize(payload, new JsonSerializerOptions { WriteIndented = true })}");

            var request = new InvokeRequest
            {
                FunctionName = _openAiFunctionName,
                InvocationType = InvocationType.RequestResponse,
                Payload = SystemJsonSerializer.Serialize(payload)
            };

            var response = await _lambdaClient.InvokeAsync(request);
            var responsePayload = SystemJsonSerializer.Deserialize<OpenAiResponse>(response.Payload);

            Console.WriteLine($"responsePayload: {System.Text.Json.JsonSerializer.Serialize(responsePayload, new JsonSerializerOptions { WriteIndented = true })}");

            if (responsePayload?.StatusCode != 200)
            {
                throw new Exception($"OpenAI Lambda function returned status code {responsePayload?.StatusCode}. Error: {SystemJsonSerializer.Serialize(responsePayload?.Body?.Error)}");
            }

            return responsePayload?.Body?.Choices?[0].Message?.Content ?? string.Empty;
        }

        private async Task SendResultToWordPress(ResultToWordPress result)
        {
            var postData = SystemJsonSerializer.Serialize(result);
            var content = new StringContent(postData, System.Text.Encoding.UTF8, "application/json");

            var response = await HttpClient.PostAsync("https://promptintellect.com/wp-json/product-extension/v1/lambda-results", content);

            if (!response.IsSuccessStatusCode)
            {
                throw new Exception($"Failed to send result to WordPress. Status code: {response.StatusCode}");
            }
        }
    }

    public class LambdaInput
    {
        [JsonPropertyName("execution_id")]
        public string ExecutionId { get; set; } = string.Empty; // Default to empty string if not provided

        [JsonPropertyName("user_id")]
        public int UserId { get; set; } = 0; // Default to 0 if not provided

        [JsonPropertyName("product_id")]
        public int ProductId { get; set; } = 0; // Default to 0 if not provided

        [JsonPropertyName("vendor_id")]
        public string VendorId { get; set; } = string.Empty; // Default to empty string if not provided

        [JsonPropertyName("token")]
        public string Token { get; set; } = string.Empty; // Default to empty string if not provided

        [JsonPropertyName("custom_inputs")]
        public CustomInputs CustomInputs { get; set; } = new CustomInputs(); // Ensure it's never null
    }

    public class CustomInputs
    {
        [JsonPropertyName("business_name")]
        public string BusinessName { get; set; } = string.Empty; // Default to empty string

        [JsonPropertyName("website_url")]
        public string WebsiteUrl { get; set; } = string.Empty; // Default to empty string

        [JsonPropertyName("target")]
        public string Target { get; set; } = string.Empty; // Default to empty string
    }

    public class ResponseBody
    {
        [JsonPropertyName("message")]
        public string? Message { get; set; }

        [JsonPropertyName("error")]
        public string? Error { get; set; }
    }

    public class LambdaResponse
    {
        [JsonPropertyName("statusCode")]
        public int StatusCode { get; set; }

        [JsonPropertyName("body")]
        public string? Body { get; set; }
    }

    public class ResultToWordPress
    {
        [JsonPropertyName("execution_id")]
        public string ExecutionId { get; set; }

        [JsonPropertyName("user_id")]
        public int UserId { get; set; }

        [JsonPropertyName("product_id")]
        public int ProductId { get; set; }

        [JsonPropertyName("token")]
        public string Token { get; set; }

        [JsonPropertyName("status")]
        public string Status { get; set; }

        [JsonPropertyName("results")]
        public string Results { get; set; }
    }

    public class OpenAiResponse
    {
        [JsonPropertyName("status_code")]
        public int StatusCode { get; set; }

        [JsonPropertyName("body")]
        public OpenAiResponseBody? Body { get; set; }
    }

    public class OpenAiResponseBody
    {
        [JsonPropertyName("choices")]
        public Choice[]? Choices { get; set; }

        [JsonPropertyName("error")]
        public string? Error { get; set; }
    }

    public class Choice
    {
        [JsonPropertyName("message")]
        public Message? Message { get; set; }
    }

    public class Message
    {
        [JsonPropertyName("content")]
        public string? Content { get; set; }
    }
}
