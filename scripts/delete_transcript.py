#!/usr/bin/env python3
"""
Delete specific transcript chunks from ChromaDB by meeting name
"""
import sys
import os
from pathlib import Path

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import chromadb
from app.core.config import settings
from dotenv import load_dotenv

load_dotenv()


def delete_transcript_by_meeting_name(project_id: int, meeting_name: str):
    """Delete all chunks for a specific meeting"""
    
    print("=" * 60)
    print(f"Deleting transcript: {meeting_name} from project_{project_id}")
    print("=" * 60)
    
    try:
        # Connect to ChromaDB
        print(f"\n🔌 Connecting to ChromaDB at {settings.CHROMA_HOST}:{settings.CHROMA_PORT}...")
        client = chromadb.HttpClient(
            host=settings.CHROMA_HOST,
            port=settings.CHROMA_PORT
        )
        
        collection_name = f"project_{project_id}"
        
        # Get the collection
        try:
            collection = client.get_collection(name=collection_name)
            print(f"✅ Found collection: {collection_name}")
        except Exception as e:
            print(f"❌ Collection not found: {collection_name}")
            return
        
        # Get all chunks with this meeting_name
        print(f"\n🔍 Searching for chunks with meeting_name='{meeting_name}'...")
        results = collection.get(
            where={"meeting_name": meeting_name},
            include=[]
        )
        
        print(f"Found {len(results['ids'])} chunks:")
        for chunk_id in results['ids']:
            print(f"  - {chunk_id}")
        
        # Delete them
        if results['ids']:
            print(f"\n🗑️  Deleting {len(results['ids'])} chunks...")
            collection.delete(ids=results['ids'])
            print(f"✅ Successfully deleted {len(results['ids'])} chunks from ChromaDB")
            
            # Verify
            count = collection.count()
            print(f"📊 Collection '{collection_name}' now has {count} total chunks")
        else:
            print("⚠️  No chunks found to delete")
    
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python delete_transcript.py <project_id> <meeting_name>")
        print("Example: python delete_transcript.py 1 testmeet")
        sys.exit(1)
    
    project_id = int(sys.argv[1])
    meeting_name = sys.argv[2]
    
    delete_transcript_by_meeting_name(project_id, meeting_name)
