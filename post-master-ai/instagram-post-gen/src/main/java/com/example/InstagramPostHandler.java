package com.example;

import com.amazonaws.services.lambda.runtime.Context;
import com.amazonaws.services.lambda.runtime.RequestHandler;
import com.amazonaws.services.lambda.runtime.LambdaLogger;

import com.amazonaws.services.s3.AmazonS3;
import com.amazonaws.services.s3.AmazonS3ClientBuilder;
import com.amazonaws.services.lambda.AWSLambda;
import com.amazonaws.services.lambda.AWSLambdaClientBuilder;
import com.amazonaws.services.lambda.model.InvokeRequest;
import com.amazonaws.services.lambda.model.InvokeResult;

import org.apache.http.HttpEntity;
import org.apache.http.client.methods.CloseableHttpResponse;
import org.apache.http.client.methods.HttpGet;
import org.apache.http.client.methods.HttpPost;
import org.apache.http.entity.StringEntity;
import org.apache.http.impl.client.CloseableHttpClient;
import org.apache.http.impl.client.HttpClients;
import org.apache.http.util.EntityUtils;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.core.type.TypeReference;

import java.nio.charset.StandardCharsets;
import java.nio.ByteBuffer;
import java.util.Map;
import java.util.function.Function;
import java.util.regex.MatchResult;
import java.util.HashMap;
import java.util.List;
import java.io.IOException;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.stream.Collectors;

import org.commonmark.node.*;
import org.commonmark.parser.Parser;
import org.commonmark.renderer.html.HtmlRenderer;

import emoji4j.EmojiUtils;

public class InstagramPostHandler implements RequestHandler<Map<String, Object>, Map<String, Object>> {

    private final AmazonS3 s3Client = AmazonS3ClientBuilder.defaultClient();
    private final AWSLambda lambdaClient = AWSLambdaClientBuilder.defaultClient();
    private final ObjectMapper objectMapper = new ObjectMapper();

    @Override
    public Map<String, Object> handleRequest(Map<String, Object> event, Context context) {
        LambdaLogger logger = context.getLogger();
        Map<String, Object> response = new HashMap<>();

        try {
            // Extract environment variables
            String bucketName = System.getenv("PI_EXECUTION_S3_BUCKET_NAME");
            String resultFolder = System.getenv("PI_RESULTS_FOLDER");
            String openaiFunction = System.getenv("PI_OPENAI_FUNCTION");

            // Extract event data
            String executionId = (String) event.get("execution_id");
            Integer userId = (Integer) event.get("user_id");
            Integer productId = (Integer) event.get("product_id");
            String token = (String) event.get("token");
            Map<String, String> customInputs = (Map<String, String>) event.get("custom_inputs");
            String explanation = customInputs.getOrDefault("explanation", "");

            // Generate Instagram post caption
            String captionPrompt = "Create an Instagram post caption based on the following explanation:\n\n" + explanation;
            String openaiCaptionResult = invokeOpenaiLambda(executionId, userId, productId, captionPrompt, "chat-gpt-4o", "1x", openaiFunction, logger);
            Map<String, Object> openaiCaptionMap = objectMapper.readValue(openaiCaptionResult, new TypeReference<Map<String, Object>>() {});
            String caption = (String) ((Map<String, Object>) ((Map<String, Object>) ((List<Object>) openaiCaptionMap.get("choices")).get(0)).get("message")).get("content");

            // Generate Instagram post image
            String imagePrompt = "Generate an image based on the following explanation, this image will be used for non-commercial purposes:\n\n" + explanation;
            String openaiImageResult = invokeOpenaiLambda(executionId, userId, productId, imagePrompt, "image-dall-e-3", "1x", openaiFunction, logger);
            Map<String, Object> openaiImageMap = objectMapper.readValue(openaiImageResult, new TypeReference<Map<String, Object>>() {});
            String imageUrl = (String) ((Map<String, Object>) ((List<Object>) openaiImageMap.get("data")).get(0)).get("url");

            // Upload the image to S3
            String uploadedImageKey = downloadAndUploadToS3(imageUrl, bucketName, resultFolder + "/" + executionId, logger);

            // Prepare the result
            String htmlMessage = generateHtmlMessage(executionId, userId, productId, caption);

            Map<String, Object> result = new HashMap<>();
            result.put("execution_id", executionId);
            result.put("user_id", userId);
            result.put("product_id", productId);
            result.put("token", token);
            result.put("status", "successful");
            result.put("results", htmlMessage);

            // Send the result to the endpoint
            sendResultToWordpress(result, logger);

            response.put("statusCode", 200);
            response.put("body", "{\"message\": \"Task executed successfully\"}");
        } catch (Exception e) {
            logger.log("Error: " + e.getMessage());

            Map<String, Object> errorResult = new HashMap<>();
            errorResult.put("execution_id", event.get("execution_id"));
            errorResult.put("user_id", event.get("user_id"));
            errorResult.put("product_id", event.get("product_id"));
            errorResult.put("token", event.get("token"));
            errorResult.put("status", "failed");
            errorResult.put("results", "<div style=\"padding: 20px; color: #ff3333; background-color: #fec4c4; border-radius: 5px;\"><p><strong>Error: </strong>" + e.getMessage() + "</p></div>");

            try {
                sendResultToWordpress(errorResult, logger);
            } catch (IOException ioException) {
                context.getLogger().log("Failed to send result to WordPress: " + ioException.getMessage());
            }

            response.put("statusCode", 500);
            response.put("body", "{\"message\": \"" + e.getMessage() + "\"}");
        }

        return response;
    }

    private String invokeOpenaiLambda(String executionId, Integer userId, Integer productId, String prompt, String service, String size, String openaiFunction, LambdaLogger logger) throws IOException {
        Map<String, Object> openaiPayload = new HashMap<>();
        openaiPayload.put("execution_id", executionId);
        openaiPayload.put("user_id", userId);
        openaiPayload.put("product_id", productId);
        openaiPayload.put("service", service);
        openaiPayload.put("size", size);
        openaiPayload.put("prompt", prompt);

        InvokeRequest invokeRequest = new InvokeRequest()
                .withFunctionName(openaiFunction)
                .withPayload(objectMapper.writeValueAsString(openaiPayload));
        InvokeResult invokeResult = lambdaClient.invoke(invokeRequest);

        String responsePayload = new String(invokeResult.getPayload().array(), StandardCharsets.UTF_8);
        Map<String, Object> responseMap = objectMapper.readValue(responsePayload, new TypeReference<Map<String, Object>>() {});
        int statusCode = (int) responseMap.get("status_code");
        if (statusCode != 200) {
            throw new RuntimeException("OpenAI Lambda function returned status code " + statusCode + " with body " + responseMap.get("body"));
        }

        return objectMapper.writeValueAsString(responseMap.get("body"));
    }

    private String downloadAndUploadToS3(String url, String bucketName, String folderPath, LambdaLogger logger) throws IOException {
        CloseableHttpClient httpClient = HttpClients.createDefault();
        HttpGet httpGet = new HttpGet(url);
        CloseableHttpResponse response = httpClient.execute(httpGet);

        try {
            HttpEntity entity = response.getEntity();
            if (entity != null) {
                String baseUrl = url.split("\\?")[0];
                String[] urlParts = baseUrl.split("/");
                String fileName = urlParts[urlParts.length - 1];
                String fullPath = folderPath + "/" + fileName;
                s3Client.putObject(bucketName, fullPath, entity.getContent(), null);
                logger.log("File " + fullPath + " uploaded to S3 bucket " + bucketName);
                return fullPath;
            } else {
                throw new RuntimeException("Failed to download image from URL");
            }
        } finally {
            response.close();
        }
    }

    private String generateHtmlMessage(String executionId, Integer userId, Integer productId, String caption) {
        String markdownHtml = markdownToHtml(caption);
        String finalHtml = EmojiUtils.hexHtmlify(markdownHtml);
        return "<div style=\"padding: 20px; background-color: #f0f0f0; border-radius: 5px;\">" +
                "<h2>Instagram Post Creation Result</h2>" +
                "<p><strong>Execution ID:</strong> " + executionId + "</p>" +
                "<p><strong>User ID:</strong> " + userId + "</p>" +
                "<p><strong>Product ID:</strong> " + productId + "</p>" +
                "<p><strong>Caption:</strong><br><pre>" + finalHtml + "</pre></p>" +
                "</div>";
    }

    private String escape(String s) {
        return s.codePoints()
            .mapToObj(codePoint -> codePoint > 127 ?
                "&#x" + Integer.toHexString(codePoint) + ";" :
                 new String(Character.toChars(codePoint)))
        .collect(Collectors.joining());
    }

    private String markdownToHtml(String markdown) {
        HtmlRenderer renderer = HtmlRenderer.builder().build();
        Parser parser = Parser.builder().build();
        Node document = parser.parse(markdown);

        return renderer.render(document);
    }

    private void sendResultToWordpress(Map<String, Object> result, LambdaLogger logger) throws IOException {
        CloseableHttpClient httpClient = HttpClients.createDefault();
        HttpPost httpPost = new HttpPost("https://promptintellect.com/wp-json/product-extension/v1/lambda-results");
        httpPost.setHeader("Content-Type", "application/json");
        httpPost.setEntity(new StringEntity(objectMapper.writeValueAsString(result)));

        CloseableHttpResponse response = httpClient.execute(httpPost);
        if (response.getStatusLine().getStatusCode() != 200) {
            throw new RuntimeException("Unexpected status code: " + response.getStatusLine().getStatusCode());
        }

        response.close();
    }
}
