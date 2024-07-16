const AWS = require('aws-sdk');
const https = require('https');
const { PDFDocument, rgb } = require('pdf-lib');
const s3 = new AWS.S3();
const lambda = new AWS.Lambda();

exports.handler = async (event) => {
  const {
    execution_id,
    user_id,
    product_id,
    token,
    custom_inputs: {
      goal,
      experience_level,
      preferred_workout_time,
      available_equipment,
      workout_frequency,
      age,
      weight,
      height,
      health_conditions
    }
  } = event;

  const bucketName = process.env.PI_EXECUTION_S3_BUCKET_NAME;
  const resultFolder = process.env.PI_RESULTS_FOLDER;

  try {
    const prompt = generatePrompt({
      goal,
      experience_level,
      preferred_workout_time,
      available_equipment,
      workout_frequency,
      age,
      weight,
      height,
      health_conditions
    });

    const openaiResult = await invokeOpenAiLambda(prompt, execution_id);

    const workoutPlanHtml = generateWorkoutPlanHtml(openaiResult, {
      goal
    });

    const pdfBytes = await generatePdf(workoutPlanHtml);
    const pdfKey = `${resultFolder}/${execution_id}/program.pdf`;

    await s3.putObject({
      Bucket: bucketName,
      Key: pdfKey,
      Body: pdfBytes,
      ContentType: 'application/pdf'
    }).promise();

    const htmlMessage = generateHtmlMessage();

    await sendResultToWordPress({
      execution_id,
      user_id,
      product_id,
      token,
      status: 'successful',
      results: htmlMessage
    });

    return {
      statusCode: 200,
      body: JSON.stringify({
        message: 'Workout plan generated successfully',
        pdfUrl: `https://${bucketName}.s3.amazonaws.com/${pdfKey}`
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
        message: 'Failed to generate workout plan',
        error: error.message
      })
    };
  }
};

function generatePrompt(inputs) {
  return `
    Create a workout plan for a ${inputs.age}-year-old ${inputs.experience_level} aiming for ${inputs.goal}.
    They prefer to work out in the ${inputs.preferred_workout_time} using the following equipment: ${inputs.available_equipment}.
    The user plans to work out ${inputs.workout_frequency}.
    Their weight is ${inputs.weight} kg and height is ${inputs.height} cm.
    Health conditions: ${inputs.health_conditions}.
  `;
}

async function invokeOpenAiLambda(prompt, execution_id) {
  const payload = {
    execution_id,
    prompt
  };

  const response = await lambda.invoke({
    FunctionName: process.env.PI_OPENAI_CHAT_FUNCTION,
    InvocationType: 'RequestResponse',
    Payload: JSON.stringify(payload)
  }).promise();

  console.log(`response from OpenAI: ${JSON.stringify(response, null, 2)}`);

  const responsePayload = JSON.parse(response.Payload);
  if (responsePayload.status_code !== 200) {
    throw new Error(`OpenAI Lambda function returned status code ${responsePayload.status_code}`);
  }

  const openaiBody = responsePayload.body;
  return openaiBody.choices[0].message.content;
}

function generateWorkoutPlanHtml(openaiResult, inputs) {
  const { goal } = inputs;
  return `
    <div style="padding: 20px; background-color: #f0f0f0; border-radius: 5px;">
        <h2>Personalized Workout Plan</h2>
        <p><strong>Goal:</strong> ${goal}</p>
        <div>${openaiResult}</div>
        <h3>Word of Caution</h3>
        <p>Please consult with a healthcare professional before starting any new exercise program. Stay hydrated and listen to your body.</p>
    </div>
  `;
}

async function generatePdf(htmlContent) {
  const pdfDoc = await PDFDocument.create();
  const page = pdfDoc.addPage([600, 400]);

  page.drawText(htmlContent, {
    x: 50,
    y: 350,
    size: 12,
    color: rgb(0, 0, 0)
  });

  return await pdfDoc.save();
}

function generateHtmlMessage() {
  return `
    <div style="padding: 20px; background-color: #f0f0f0; border-radius: 5px;">
        <h2>Your program is ready!</h2>
        <h3>Word of Caution</h3>
        <p>Please consult with a healthcare professional before starting any new exercise program. Stay hydrated and listen to your body.</p>
    </div>
  `;
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
