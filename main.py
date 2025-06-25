import os, random, httpx, requests
from pprint import pprint
import uvicorn, json
import schemas
from uuid import uuid4
from fastapi import FastAPI, Request, status, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse
from a2a.utils import new_agent_text_message
from dotenv import load_dotenv
from datetime import datetime
# Load environment variables from .env file

load_dotenv()

TELEX_API_KEY = os.getenv('TELEX_API_KEY')
TELEX_API_URL = os.getenv('TELEX_API_URL')
TELEX_AI_URL = os.getenv('TELEX_AI_URL')
TELEX_AI_MODEL = os.getenv('TELEX_AI_MODEL')
TELEX_ORG_ID = os.getenv('TELEX_ORG_ID')

PORT = int(os.getenv("PORT", 4000))

app = FastAPI()

RAW_AGENT_CARD_DATA = {
  "name": "Conversational Memory Agent",
  "description": "An agent that can remember and recall information using a database and understand user intent with the AI.",
  "url": "",
  "provider": {
      "organization": "Telex Org.",
      "url": "https://telex.im"
    },
  "version": "1.0.0",
  "documentationUrl": "",
  "is_paid": False,
  "price": {},
  "capabilities": {
    "streaming": False,
    "pushNotifications": True
  },
  "defaultInputModes": ["text/plain"],
  "defaultOutputModes": ["text/plain"],
  "skills": [
    {
      "id": "convo",
      "name": "Conversation",
      "description": "Responds to user input with meaningful related output.",
      "inputModes": ["text"],
      "outputModes": ["text"],
      "examples": [
        {
          "input": { "parts": [{ "text": "Hello", "contentType": "text/plain" }] },
          "output": { "parts": [{ "text": "Hi, how are you?", "contentType": "text/plain" }] }
        }
      ]
    },
    {
      "id": "storage",
      "name": "Information storage",
      "description": "Stores important information or facts sent by the user",
      "inputModes": ["text"],
      "outputModes": ["text"],
      "examples": [
        {
          "input": { "parts": [{ "text": "Hello, my name is Idara. My favorite color is blue", "contentType": "text/plain" }] },
          "output": { "parts": [{ "text": "Hi, Idara, nice to meet you", "contentType": "text/plain" }] }
        },
        {
          "input": { "parts": [{ "text": "What is my favorite color?", "contentType": "text/plain" }] },
          "output": { "parts": [{ "text": "Your favorite color is blue.", "contentType": "text/plain" }] }
        }
      ]
    }
  ]
}


@app.get("/", response_class=HTMLResponse)
def read_root():
    return '<p style="font-size:30px">AI Agent</p>'


@app.get("/.well-known/agent.json")
def agent_card(request: Request):
    external_base = request.headers.get("x-external-base-url", "")
    current_base_url = str(request.base_url).rstrip("/") + external_base

    response_agent_card = RAW_AGENT_CARD_DATA.copy()

    response_agent_card["url"] = current_base_url
    response_agent_card["provider"]["url"] = current_base_url
    response_agent_card["provider"]["documentationUrl"] = f"{current_base_url}/docs"

    return response_agent_card

async def analyze_intent_with_ai(user_message: str):
    """
    Uses AI to analyze the user's message to determine intent.
    The AI will classify the intent and extract relevant data.
    """
    
    prompt = f"""
    Analyze the following user message to determine the user's intent.
    The intent can be one of three types:
    1. 'remember': The user is stating a fact to be remembered.
    2. 'recall': The user is asking a question about something they previously stated.
    3. 'chat': The user is making a general conversational statement.

    Your response MUST be a JSON object with the following structure:
    - For 'remember' intent: {{"intent": "remember", "data": {{"key": "<the fact category>", "value": "<the fact value>"}}}}
    - For 'recall' intent: {{"intent": "recall", "data": {{"key": "<the fact category to recall>"}}}}
    - For 'chat' intent: {{"intent": "chat", "data": {{"key": "reply", "value": "<a natural reply to the input message>"}}}}

    Examples:
    - User message: "my name is Mark" -> {{"intent": "remember", "data": {{"key": "name", "value": "Mark"}}}}
    - User message: "my favorite color is blue" -> {{"intent": "remember", "data": {{"key": "favorite color", "value": "blue"}}}}
    - User message: "what is my name?" -> {{"intent": "recall", "data": {{"key": "name"}}}}
    - User message: "what's my favourite colour?" -> {{"intent": "recall", "data": {{"key": "favorite color"}}}}
    - User message: "hello there" -> {{"intent": "chat", "data": {{"key": "reply", "value": "Hello to you too"}}}}

    Now, analyze this message:
    User message: "{user_message}"
    """

    try:
      async with httpx.AsyncClient(timeout=5.0) as client:
        request_headers = {
          "X-AGENT-API-KEY": TELEX_API_KEY,
          "X-MODEL": TELEX_AI_MODEL
        }
        print(f"Request headers: {request_headers}")

        request_body = {
          "organisation_id": "01971783-a2ff-78b2-bd02-d9ddf8fb23c6",
          "model": "openai/gpt-4.1",
          "messages": [
            {
              "role": "system",
              "content": prompt
            }
          ],
          "stream": False
        }

        response = await client.post(
          TELEX_AI_URL, 
          headers=request_headers,
          json=request_body
        )

        pprint(response.json())
        response.raise_for_status()
        # Extract the JSON string from the AI's response
        res = response.json().get("data", {}).get("Messages", None)
        reply = res.get("content", "not available")
        
        return json.loads(reply)

    except (KeyError, IndexError, json.JSONDecodeError) as e:
        print(f"Error parsing AI response: {e}")
        print(f"Raw AI response was: {reply}")
        raise HTTPException(status_code=500, detail="Could not understand the AI model's response.")


async def res_based_on_intent(payload, user_id):
  intent = payload["intent"]
  data = payload["data"]
   # Step 2: Act based on the analyzed intent
  if intent == "remember":
    key = data.get("key")
    value = data.get("value")

    if not key or not value:
        response_message = "I think you want me to remember something, but I couldn't figure out what."

    else:
      async with httpx.AsyncClient() as client:
        headers = {"X-AGENT-API-KEY": TELEX_API_KEY}
        body = {
          "document": {
            "type": "user_information",
            "user_id": user_id,
            "key": key,
            "value": value,
            "created_at": datetime.now().isoformat(),
          }
        }
        is_sent = await client.post(f"{TELEX_API_URL}/agent_db/collections/user_information/documents", headers=headers, json=body)
        pprint(is_sent.json())

        is_sent.raise_for_status()
        response_message = f"Okay, I'll remember that your {key} is {value}."

  elif intent == "recall":
    key = data.get("key")

    if not key:
      response_message = "I think you're asking a question, but I'm not sure what about."

    else:
      # Find the user's memory document
      user_memory = None
      async with httpx.AsyncClient() as client:
        headers = {"X-AGENT-API-KEY": TELEX_API_KEY}
        data = { 
          "filter": {
            "organisation_id": TELEX_ORG_ID,
            "type": "user_information", 
            "user_id": user_id,
            "key": key
          }
        }
        response = requests.get(
          url=f"{TELEX_API_URL}/agent_db/collections/user_information/documents", 
          headers=headers, 
          json=data
        )
        # user_memory = await client.get(
        #   f"{TELEX_API_URL}/agent_db/collections/user_information/documents", 
        #   headers=headers, 
        #   content=filter
        # )

        pprint(response.json())
        response.raise_for_status()
        user_memory = response.json().get("data", [])

        match = list(filter(lambda doc: doc.get("key") == key, user_memory))

        if match:
          recalled_value = match[0]["value"]
          response_message = f"You told me your {key} is {recalled_value}."
        else:
            response_message = f"I don't think you've told me your {key} yet."

  elif intent == "chat":
    response_message = data.get("value", "I'm not sure how to respond to that.")

  else:
    response_message = "I'm not quite sure how to respond to that."

  return response_message


async def handle_task(message:str, request_id, context_id:str, task_id: str, webhook_url: str):
  print("telex api url:", TELEX_API_URL)
  #attempt to create mongodb collection
  async with httpx.AsyncClient() as client:
    headers = {"X-AGENT-API-KEY": TELEX_API_KEY}
    body = {
      "collection": "user_information"
    }
    is_created = await client.post(f"{TELEX_API_URL}/agent_db/collections", headers=headers, json=body)
    pprint(is_created.json())

    if is_created.status_code not in [200, 400]:
      raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Failed to create or access the user information collection."
      )

  intent = await analyze_intent_with_ai(message)

  response = await res_based_on_intent(intent, context_id)

  parts = schemas.TextPart(text=response)

  message = schemas.Message(role="agent", parts=[parts])

  artifacts = schemas.Artifact(parts=[parts])

  task = schemas.Task(
    id = task_id,
    status =  schemas.TaskStatus(
      state=schemas.TaskState.COMPLETED, 
      message=schemas.Message(role="agent", parts=[schemas.TextPart(text=response)])
    ),
    artifacts = [artifacts]
  )

  webhook_response = schemas.SendResponse(
      id=request_id,
      result=task
  )

  pprint(webhook_response.model_dump())


  async with httpx.AsyncClient() as client:
    headers = {"X-TELEX-API-KEY": TELEX_API_KEY}
    is_sent = await client.post(webhook_url, headers=headers,  json=webhook_response.model_dump(exclude_none=True))
    pprint(is_sent.json())

  print("background done")
  return 



@app.post("/")
async def handle_request(request: Request, background_tasks: BackgroundTasks):
  try:
    body = await request.json()

  except json.JSONDecodeError as e:
    error = schemas.JSONParseError(
      data = str(e)
    )
    response = schemas.JSONRPCResponse(
       error=error
    )

  request_id = body.get("id")
  user_id = body["params"]["message"]["metadata"].get("telex_user_id", None)  
  webhook_url = body["params"]["configuration"]["pushNotificationConfig"]["url"]

  message = body["params"]["message"]["parts"][0].get("text", None)

  if not message:
    raise HTTPException(
      status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
      detail="Message cannot be empty."
    )
  
  new_task = schemas.Task(
    id = uuid4().hex,
    status =  schemas.TaskStatus(
      state=schemas.TaskState.SUBMITTED, 
      message=schemas.Message(role="agent", parts=[schemas.TextPart(text="In progress")])
    )
  )
  
  background_tasks.add_task(handle_task, message, request_id, user_id, new_task.id, webhook_url)

  response = schemas.JSONRPCResponse(
      id=request_id,
      result=new_task
  )

  # except Exception as e:
  #   error = schemas.JSONRPCError(
  #     code = -32600,
  #     message = str(e)
  #   )

  #   request = await request.json()
  #   response = schemas.JSONRPCResponse(
  #      id=request.get("id"),
  #      error=error
  #   )

  response = response.model_dump(exclude_none=True)
  pprint(response)
  return response


if __name__ == "__main__":
    port = int(os.getenv("PORT", 10000))
    uvicorn.run("main:app", host="127.0.0.1", port=PORT, reload=True)
