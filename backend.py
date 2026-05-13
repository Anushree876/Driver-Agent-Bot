"""
backend.py — FastAPI + LangChain Agent + Google Drive Search Tool

HOW IT WORKS:
1. User sends a message to POST /chat
2. LangChain agent (powered by Groq LLM) reads the message
3. LLM decides to call DriveSearchTool with a proper `q` query string
4. Tool hits Google Drive API files.list with that query
5. Results come back to LLM, which formats a nice response
6. Response sent back to Streamlit frontend

SETUP:
  pip install fastapi uvicorn langchain langchain-groq langchain-core \
              google-api-python-client google-auth pydantic python-dotenv

ENV VARIABLES NEEDED (.env file):
  GROQ_API_KEY=your_groq_api_key
  GOOGLE_SERVICE_ACCOUNT_JSON=path/to/your/service_account.json
  DRIVE_FOLDER_ID=your_shared_folder_id

RUN:
  uvicorn backend:app --reload --port 8000
"""

import os
import json
from typing import Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

# LangChain imports
from langchain_groq import ChatGroq
from langchain.tools import tool
from langchain.agents import create_tool_calling_agent, AgentExecutor
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.messages import HumanMessage, AIMessage

# Google Drive imports
from googleapiclient.discovery import build
from google.oauth2 import service_account

load_dotenv()

# ─────────────────────────────────────────────
# 1. GOOGLE DRIVE SETUP
# ─────────────────────────────────────────────

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
FOLDER_ID = os.getenv("DRIVE_FOLDER_ID", "")

SERVICE_ACCOUNT_INFO = json.loads(
    os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON_CONTENT", "{}")
)
def get_drive_service():
    """Build and return a Google Drive API service object using service account."""
    creds = service_account.Credentials.from_service_account_info(
    SERVICE_ACCOUNT_INFO,
    scopes=SCOPES
)
    return build("drive", "v3", credentials=creds)


# ─────────────────────────────────────────────
# 2. THE DRIVE SEARCH TOOL (LangChain @tool)
# ─────────────────────────────────────────────

@tool
def search_drive_files(query: str) -> str:
    """
    Search for files in Google Drive using a Drive API query string.

    Use this tool whenever the user wants to find, list, or discover files.

    The `query` parameter must be a valid Google Drive API `q` string. Examples:
      - name contains 'report'
      - mimeType = 'application/pdf'
      - fullText contains 'budget'
      - name contains 'invoice' and mimeType = 'application/pdf'
      - modifiedTime > '2024-01-01T00:00:00'
      - name contains 'photo' and mimeType contains 'image'

    Supported MIME types:
      - PDF:           application/pdf
      - Google Doc:    application/vnd.google-apps.document
      - Google Sheet:  application/vnd.google-apps.spreadsheet
      - Google Slides: application/vnd.google-apps.presentation
      - Image (any):   image/  (use mimeType contains 'image/')
      - Word doc:      application/vnd.openxmlformats-officedocument.wordprocessingml.document

    Always scope the search to the shared folder using the 'in parents' condition
    — this is handled automatically, you just provide the filter conditions.
    """
    try:
        service = get_drive_service()

        # Always scope to the designated folder
        folder_scope = f"'{FOLDER_ID}' in parents" if FOLDER_ID else ""
        full_query = f"({query}) and {folder_scope} and trashed = false" if folder_scope else f"({query}) and trashed = false"

        results = service.files().list(
            q=full_query,
            pageSize=20,
            fields="files(id, name, mimeType, modifiedTime, size, webViewLink)",
            orderBy="modifiedTime desc"
        ).execute()

        files = results.get("files", [])

        if not files:
            return "No files found matching your search criteria."

        # Format results nicely for the LLM to read
        output_lines = [f"Found {len(files)} file(s):\n"]
        for f in files:
            # Human-readable MIME type
            mime = f.get("mimeType", "")
            friendly_type = mime_to_label(mime)

            # Format modified time
            modified = f.get("modifiedTime", "")[:10]  # just the date part

            # Build entry
            line = (
                f"• **{f['name']}**\n"
                f"  Type: {friendly_type}\n"
                f"  Modified: {modified}\n"
                f"  Link: {f.get('webViewLink', 'N/A')}\n"
            )
            output_lines.append(line)

        return "\n".join(output_lines)

    except Exception as e:
        return f"Error searching Drive: {str(e)}"


def mime_to_label(mime: str) -> str:
    """Convert MIME type to a friendly label."""
    mapping = {
        "application/pdf": "PDF",
        "application/vnd.google-apps.document": "Google Doc",
        "application/vnd.google-apps.spreadsheet": "Google Sheet",
        "application/vnd.google-apps.presentation": "Google Slides",
        "application/vnd.google-apps.folder": "Folder",
        "image/jpeg": "JPEG Image",
        "image/png": "PNG Image",
        "image/gif": "GIF Image",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "Word Doc",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "Excel Sheet",
    }
    if mime in mapping:
        return mapping[mime]
    if "image/" in mime:
        return "Image"
    return mime  # fallback: show raw mime type


# ─────────────────────────────────────────────
# 3. LANGCHAIN AGENT SETUP
# ─────────────────────────────────────────────

SYSTEM_PROMPT = """You are a helpful Google Drive assistant. Your job is to help users 
find and discover files in their Google Drive folder.

When a user asks to find files, ALWAYS use the search_drive_files tool.
Translate their natural language request into a proper Google Drive API query string.

Query string rules:
- Use `name contains 'keyword'` for searching by partial name
- Use `name = 'exact name'` for exact match  
- Use `mimeType = 'type'` for file type filtering
- Use `fullText contains 'keyword'` to search inside file content
- Use `modifiedTime > 'YYYY-MM-DDT00:00:00'` for date filtering
- Combine with `and` / `or` operators
- Use `not` to exclude: `not mimeType = 'application/pdf'`

After getting results, present them in a clean, readable way with file names and links.
Be conversational and helpful. If no files are found, suggest alternative search terms.

Today's date: {today}
"""

# Initialize LLM
llm = ChatGroq(
    api_key=os.getenv("GROQ_API_KEY"),
    model="llama-3.3-70b-versatile",   # fast + capable
    temperature=0
)

# Tools list
tools = [search_drive_files]

# Prompt template with chat history support
prompt = ChatPromptTemplate.from_messages([
    ("system", SYSTEM_PROMPT),
    MessagesPlaceholder(variable_name="chat_history"),
    ("human", "{input}"),
    MessagesPlaceholder(variable_name="agent_scratchpad"),  # where tool calls go
])

# Create agent
agent = create_tool_calling_agent(llm, tools, prompt)

# AgentExecutor runs the ReAct loop: Think → Tool → Observe → Respond
agent_executor = AgentExecutor(
    agent=agent,
    tools=tools,
    verbose=True,   # shows reasoning in terminal (good for learning!)
    max_iterations=5
)


# ─────────────────────────────────────────────
# 4. FASTAPI APP
# ─────────────────────────────────────────────

app = FastAPI(title="Drive Search Agent", version="1.0")

# Allow Streamlit (any origin) to call this API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory conversation store: { session_id: [messages] }
# For production, use Redis or a database
conversation_store: dict[str, list] = {}


class ChatRequest(BaseModel):
    message: str
    session_id: str = "default"


class ChatResponse(BaseModel):
    reply: str
    session_id: str


@app.get("/")
def root():
    return {"status": "Drive Search Agent is running!"}


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """
    Main chat endpoint.
    Receives user message, runs LangChain agent, returns response.
    """
    from datetime import date

    session_id = request.session_id

    # Get or create conversation history
    if session_id not in conversation_store:
        conversation_store[session_id] = []

    history = conversation_store[session_id]

    # Run agent
    result = agent_executor.invoke({
        "input": request.message,
        "chat_history": history,
        "today": date.today().isoformat()
    })

    reply = result["output"]

    # Save to history (LangChain message objects)
    history.append(HumanMessage(content=request.message))
    history.append(AIMessage(content=reply))

    # Keep history to last 20 messages to avoid token overflow
    if len(history) > 20:
        conversation_store[session_id] = history[-20:]

    return ChatResponse(reply=reply, session_id=session_id)


@app.delete("/chat/{session_id}")
def clear_history(session_id: str):
    """Clear conversation history for a session."""
    conversation_store.pop(session_id, None)
    return {"status": "cleared"}


# ─────────────────────────────────────────────
# 5. RUN DIRECTLY (for development)
# ─────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend:app", host="0.0.0.0", port=8000, reload=True)