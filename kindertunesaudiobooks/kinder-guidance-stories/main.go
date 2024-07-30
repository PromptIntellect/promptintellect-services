package main

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io/ioutil"
	"log"
	"net/http"
	"os"
	"strconv"

	lambdaGo "github.com/aws/aws-lambda-go/lambda"
	"github.com/aws/aws-sdk-go/aws"
	"github.com/aws/aws-sdk-go/aws/session"
	"github.com/aws/aws-sdk-go/service/lambda"
	"github.com/aws/aws-sdk-go/service/s3"
)

// Request defines the input parameters for the Lambda function
type Request struct {
	ExecutionID  string `json:"execution_id"`
	UserID       int    `json:"user_id"`
	ProductID    int    `json:"product_id"`
	VendorID     string `json:"vendor_id"`
	Token        string `json:"token"`
	CustomInputs struct {
		Behavior      string `json:"behavior"`
		FavoriteTheme string `json:"favorite_theme"`
	} `json:"custom_inputs"`
}

// Response represents the final response structure
type Response struct {
	Message string `json:"message"`
	Story   string `json:"story"`
}

// SplitText splits the input text into parts of a specified maximum length
func SplitText(text string, maxLength int) []string {
	var parts []string
	for len(text) > maxLength {
		splitIndex := maxLength
		for i := maxLength; i > 0 && text[i] != ' '; i-- {
			splitIndex = i
		}
		parts = append(parts, text[:splitIndex])
		text = text[splitIndex:]
	}
	if len(text) > 0 {
		parts = append(parts, text)
	}
	return parts
}

// InvokeOpenAiLambda invokes the OpenAI Lambda function and returns the response
func InvokeOpenAiLambda(prompt, executionID string, productID, userID int, service, size string) ([]string, error) {
	payload := map[string]interface{}{
		"user_id":      userID,
		"product_id":   productID,
		"execution_id": executionID,
		"prompt":       prompt,
		"service":      service,
		"size":         size,
	}

	payloadBytes, err := json.Marshal(payload)
	if err != nil {
		return nil, fmt.Errorf("error marshalling payload: %v", err)
	}

	sess := session.Must(session.NewSession())
	svc := lambda.New(sess)

	resp, err := svc.Invoke(&lambda.InvokeInput{
		FunctionName: aws.String(os.Getenv("PI_OPENAI_FUNCTION")),
		Payload:      payloadBytes,
	})
	if err != nil {
		return nil, fmt.Errorf("error invoking OpenAI Lambda: %v", err)
	}

	var responsePayload map[string]interface{}
	if err := json.Unmarshal(resp.Payload, &responsePayload); err != nil {
		return nil, fmt.Errorf("error unmarshalling response payload: %v", err)
	}

	// Log the response payload for debugging
	log.Printf("OpenAI Lambda response payload: %v", responsePayload)

	if status, ok := responsePayload["status_code"].(float64); !ok || int(status) != 200 {
		return nil, fmt.Errorf("OpenAI Lambda function returned error: %v", responsePayload)
	}

	body, ok := responsePayload["body"].(map[string]interface{})
	if !ok {
		return nil, fmt.Errorf("invalid body format in response payload: %v", responsePayload)
	}

	// Check for the correct data field based on service
	var audioURLs []string
	if service == "text_to_speech-tts-1" {
		data, ok := body["data"].([]interface{})
		if !ok {
			return nil, fmt.Errorf("invalid data format in response payload: %v", responsePayload)
		}

		for _, item := range data {
			if itemMap, ok := item.(map[string]interface{}); ok {
				if url, ok := itemMap["url"].(string); ok {
					audioURLs = append(audioURLs, url)
				}
			}
		}
	} else if service == "chat-gpt-4o-mini" {
		// Handle case for story generation
		choices, ok := body["choices"].([]interface{})
		if !ok || len(choices) == 0 {
			return nil, fmt.Errorf("no choices found in response payload: %v", responsePayload)
		}
		content, ok := choices[0].(map[string]interface{})["message"].(map[string]interface{})["content"].(string)
		if !ok {
			return nil, fmt.Errorf("invalid message content format in response payload: %v", responsePayload)
		}
		return []string{content}, nil
	}

	return audioURLs, nil
}

// DownloadAndUploadAudio handles downloading the audio files from the given URLs and uploading them to S3
func DownloadAndUploadAudio(audioURLs []string, executionID string) error {
	bucketName := os.Getenv("PI_EXECUTION_S3_BUCKET_NAME")
	resultFolder := os.Getenv("PI_RESULTS_FOLDER")

	sess := session.Must(session.NewSession())
	svc := s3.New(sess)

	for index, url := range audioURLs {
		// Download the audio file
		resp, err := http.Get(url)
		if err != nil {
			return fmt.Errorf("failed to download audio from %s: %v", url, err)
		}
		defer resp.Body.Close()

		if resp.StatusCode != http.StatusOK {
			return fmt.Errorf("bad response while downloading audio: %s", resp.Status)
		}

		audioData, err := ioutil.ReadAll(resp.Body)
		if err != nil {
			return fmt.Errorf("failed to read audio data from %s: %v", url, err)
		}

		// Upload to S3
		key := fmt.Sprintf("%s/%s/audio_part_%d.mp3", resultFolder, executionID, index+1)
		_, err = svc.PutObject(&s3.PutObjectInput{
			Bucket:      aws.String(bucketName),
			Key:         aws.String(key),
			Body:        bytes.NewReader(audioData),
			ContentType: aws.String("audio/mpeg"),
		})
		if err != nil {
			return fmt.Errorf("failed to upload audio to S3: %v", err)
		}
	}
	return nil
}

// GenerateStory creates a story using the OpenAI Lambda function
func GenerateStory(req Request) (string, error) {
	storyPrompt := fmt.Sprintf("Create a very short story for kids under 8 about %s with a theme of %s.", req.CustomInputs.Behavior, req.CustomInputs.FavoriteTheme)
	storyParts, err := InvokeOpenAiLambda(storyPrompt, req.ExecutionID, req.ProductID, req.UserID, "chat-gpt-4o-mini", "2x")
	if err != nil {
		return "", err
	}
	return storyParts[0], nil // Assuming the first part is the story, modify as needed
}

// ConvertStoryToAudio converts the generated story to audio using the Text-to-Speech Lambda function
func ConvertStoryToAudio(req Request, story string) ([]string, error) {
	const maxLength = 1024 // Maximum allowed length for the input
	parts := SplitText(story, maxLength)

	var allAudioURLs []string
	bucketName := os.Getenv("PI_EXECUTION_S3_BUCKET_NAME")
	resultFolder := os.Getenv("PI_RESULTS_FOLDER")

	for _, part := range parts {
		payload := map[string]interface{}{
			"user_id":      req.UserID,
			"product_id":   req.ProductID,
			"execution_id": req.ExecutionID,
			"vendor_id":    req.VendorID, // Ensure vendor_id is included
			"input":        part,         // Ensure input data is provided
			"service":      "text_to_speech-tts-1",
			"size":         "2x",
		}

		payloadBytes, err := json.Marshal(payload)
		if err != nil {
			return nil, fmt.Errorf("error marshalling payload: %v", err)
		}

		sess := session.Must(session.NewSession())
		svc := lambda.New(sess)

		resp, err := svc.Invoke(&lambda.InvokeInput{
			FunctionName: aws.String(os.Getenv("PI_OPENAI_FUNCTION")),
			Payload:      payloadBytes,
		})
		if err != nil {
			return nil, fmt.Errorf("error invoking OpenAI Lambda: %v", err)
		}

		var responsePayload map[string]interface{}
		if err := json.Unmarshal(resp.Payload, &responsePayload); err != nil {
			return nil, fmt.Errorf("error unmarshalling response payload: %v", err)
		}

		// Log the full response payload for debugging
		log.Printf("OpenAI Lambda response payload: %v", responsePayload)

		if status, ok := responsePayload["status_code"].(float64); !ok || int(status) != 200 {
			return nil, fmt.Errorf("OpenAI Lambda function returned error: %v", responsePayload)
		}

		body, ok := responsePayload["body"].(map[string]interface{})
		if !ok {
			return nil, fmt.Errorf("invalid body format in response payload: %v", responsePayload)
		}

		// Extract file name and construct the S3 URL
		fileName, ok := body["file_name"].(string)
		if !ok {
			return nil, fmt.Errorf("file_name not found in response payload: %v", responsePayload)
		}

		// Construct the S3 URL
		audioURL := fmt.Sprintf("https://%s.s3.amazonaws.com/%s/%s", bucketName, resultFolder, fileName)
		log.Printf("Audio URL: %s", audioURL) // Log the audio URL

		allAudioURLs = append(allAudioURLs, audioURL)
	}

	return allAudioURLs, nil
}

// SendResultToWordPress sends the result to WordPress
func SendResultToWordPress(executionID string, userID, productID int, token, status, results string) error {
	result := map[string]string{
		"execution_id": executionID,
		"user_id":      strconv.Itoa(userID),
		"product_id":   strconv.Itoa(productID),
		"token":        token,
		"status":       status,
		"results":      results,
	}

	jsonData, err := json.Marshal(result)
	if err != nil {
		return fmt.Errorf("error marshalling result to JSON: %v", err)
	}

	url := "https://promptintellect.com/wp-json/product-extension/v1/lambda-results"
	req, err := http.NewRequest("POST", url, bytes.NewBuffer(jsonData))
	if err != nil {
		return fmt.Errorf("error creating HTTP request: %v", err)
	}
	req.Header.Set("Content-Type", "application/json")

	client := &http.Client{}
	resp, err := client.Do(req)
	if err != nil {
		return fmt.Errorf("error sending result to WordPress: %v", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != 200 {
		body, _ := ioutil.ReadAll(resp.Body)
		return fmt.Errorf("unexpected status code: %d, body: %s", resp.StatusCode, string(body))
	}

	return nil
}

func handler(ctx context.Context, req Request) (Response, error) {
	var res Response

	// Generate the story
	story, err := GenerateStory(req)
	if err != nil {
		log.Printf("Error generating story: %v", err)
		SendResultToWordPress(req.ExecutionID, req.UserID, req.ProductID, req.Token, "failed", fmt.Sprintf("Error generating story: %v", err))
		return res, err
	}
	res.Story = story

	// Convert the story to audio
	audioURLs, err := ConvertStoryToAudio(req, story)
	if err != nil {
		log.Printf("Error generating audio: %v", err)
		SendResultToWordPress(req.ExecutionID, req.UserID, req.ProductID, req.Token, "failed", fmt.Sprintf("Error generating audio: %v", err))
		return res, err
	}

	// Download and upload audio files to S3
	if err := DownloadAndUploadAudio(audioURLs, req.ExecutionID); err != nil {
		log.Printf("Error downloading or uploading audio: %v", err)
		SendResultToWordPress(req.ExecutionID, req.UserID, req.ProductID, req.Token, "failed", fmt.Sprintf("Error processing audio files: %v", err))
		return res, err
	}

	// Send success message to WordPress
	successMessage := "The story and audio parts are ready and have been uploaded to S3."
	if err := SendResultToWordPress(req.ExecutionID, req.UserID, req.ProductID, req.Token, "successful", successMessage); err != nil {
		log.Printf("Error sending success message to WordPress: %v", err)
		return res, err
	}

	// Set the response message
	res.Message = successMessage
	return res, nil
}

func main() {
	lambdaGo.Start(handler)
}
