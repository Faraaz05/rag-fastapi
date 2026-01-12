"""
Test script for streaming chat endpoint.
Demonstrates how to consume the Server-Sent Events (SSE) stream.
"""
import requests
import json
import sys
import time

# Configuration
BASE_URL = "http://localhost:8000"
USERNAME = "faraaz"
PASSWORD = "far@123"
PROJECT_ID = 1
SESSION_ID = "test_session_001"


def login(username: str, password: str) -> str:
    """Login and get JWT token."""
    print("🔐 Logging in...")
    response = requests.post(
        f"{BASE_URL}/auth/token",
        data={"username": username, "password": password}
    )
    
    if response.status_code != 200:
        print(f"❌ Login failed: {response.text}")
        sys.exit(1)
    
    token = response.json()["access_token"]
    print("✅ Login successful\n")
    return token


def stream_chat(token: str, project_id: int, session_id: str, question: str, filter_type: str = "unified", top_k: int = 5):
    """
    Stream chat response from the endpoint.
    """
    print("=" * 80)
    print(f"💬 STREAMING CHAT")
    print("=" * 80)
    print(f"📝 Question: {question}")
    print(f"🔍 Filter: {filter_type}")
    print(f"📊 Top K: {top_k}")
    print(f"🎯 Session: {session_id}")
    print("=" * 80)
    print()
    
    url = f"{BASE_URL}/projects/{project_id}/chat/{session_id}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "text/event-stream"
    }
    payload = {
        "question": question,
        "filter": filter_type,
        "top_k": top_k
    }
    
    print("🤖 Assistant: ", end="", flush=True)
    
    full_answer = ""
    citations = []
    chunks_metadata = {}
    
    try:
        with requests.post(url, json=payload, headers=headers, stream=True) as response:
            if response.status_code != 200:
                print(f"\n❌ Error: {response.status_code} - {response.text}")
                return
            
            for line in response.iter_lines():
                if line:
                    line = line.decode('utf-8')
                    
                    # SSE format: "data: {json}"
                    if line.startswith('data: '):
                        data_str = line[6:]  # Remove "data: " prefix
                        
                        # Check for done signal
                        if data_str.strip() == '[DONE]':
                            print("\n\n✅ Stream completed")
                            break
                        
                        try:
                            data = json.loads(data_str)
                            
                            # Handle different event types
                            if data.get('type') == 'text':
                                # Stream text to console
                                content = data.get('content', '')
                                print(content, end="", flush=True)
                                full_answer += content
                            
                            elif data.get('type') == 'metadata':
                                # Final metadata event with citations
                                citations = data.get('citations', [])
                                chunks_metadata = data.get('chunks_metadata', {})
                            
                            elif data.get('type') == 'error':
                                print(f"\n❌ Error: {data.get('message')}")
                                return
                        
                        except json.JSONDecodeError:
                            # Skip invalid JSON
                            pass
        
        # Display citations
        if citations:
            print("\n")
            print("=" * 80)
            print("📚 CITATIONS")
            print("=" * 80)
            for i, citation in enumerate(citations, 1):
                print(f"\n[{i}] Source Type: {citation.get('source_type')}")
                
                if citation.get('source_type') == 'document':
                    print(f"    Document: {citation.get('document_name')}")
                    print(f"    Page: {citation.get('page_number')}")
                    if citation.get('positions'):
                        print(f"    Positions: {len(citation.get('positions', []))} bounding boxes")
                
                elif citation.get('source_type') == 'transcript':
                    print(f"    Meeting: {citation.get('meeting_name')}")
                    print(f"    Date: {citation.get('meeting_date')}")
                    print(f"    Time: {citation.get('start_time')} - {citation.get('end_time')}")
                    print(f"    Speakers: {', '.join(citation.get('speakers', []))}")
            
            print("=" * 80)
        
    except requests.exceptions.RequestException as e:
        print(f"\n❌ Request failed: {e}")
    except KeyboardInterrupt:
        print("\n\n⚠️  Stream interrupted by user")


def get_chat_history(token: str, project_id: int, session_id: str):
    """
    Retrieve and display chat history for a session.
    """
    print("\n" + "=" * 80)
    print("📜 CHAT HISTORY")
    print("=" * 80)
    
    url = f"{BASE_URL}/projects/{project_id}/chat/{session_id}/history"
    headers = {"Authorization": f"Bearer {token}"}
    
    response = requests.get(url, headers=headers)
    
    if response.status_code != 200:
        print(f"❌ Error fetching history: {response.text}")
        return
    
    messages = response.json()
    
    if not messages:
        print("No messages in this session yet.")
        return
    
    for msg in messages:
        role = msg['role'].upper()
        content = msg['content']
        timestamp = msg['timestamp']
        
        print(f"\n[{timestamp}] {role}:")
        print(f"  {content[:200]}{'...' if len(content) > 200 else ''}")
    
    print("=" * 80)


def interactive_chat(token: str, project_id: int, session_id: str):
    """
    Interactive chat mode - ask multiple questions in the same session.
    """
    print("\n" + "=" * 80)
    print("🚀 INTERACTIVE CHAT MODE")
    print("=" * 80)
    print("Type your questions below. Type 'exit' to quit, 'history' to view chat history.")
    print("=" * 80)
    print()
    
    while True:
        try:
            question = input("You: ").strip()
            
            if not question:
                continue
            
            if question.lower() == 'exit':
                print("👋 Goodbye!")
                break
            
            if question.lower() == 'history':
                get_chat_history(token, project_id, session_id)
                continue
            
            # Stream the chat response
            stream_chat(token, project_id, session_id, question)
            print()
        
        except KeyboardInterrupt:
            print("\n\n👋 Chat session ended")
            break


def main():
    """
    Main function to test streaming chat.
    """
    print("=" * 80)
    print("🧪 STREAMING CHAT TEST SCRIPT")
    print("=" * 80)
    print()
    
    # Login
    token = login(USERNAME, PASSWORD)
    
    # Choose mode
    print("Select mode:")
    print("1. Single question test")
    print("2. Interactive chat mode")
    print("3. View chat history only")
    
    choice = input("\nEnter choice (1/2/3): ").strip()
    
    if choice == "1":
        # Single question test
        question = input("\nEnter your question: ").strip()
        if question:
            stream_chat(token, PROJECT_ID, SESSION_ID, question)
    
    elif choice == "2":
        # Interactive mode
        interactive_chat(token, PROJECT_ID, SESSION_ID)
    
    elif choice == "3":
        # View history only
        get_chat_history(token, PROJECT_ID, SESSION_ID)
    
    else:
        print("❌ Invalid choice")


if __name__ == "__main__":
    main()
