#!/usr/bin/env python3
"""
Empty ChromaDB Database
Deletes all collections from ChromaDB
"""
import sys
import os

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import chromadb
from app.core.config import settings
from dotenv import load_dotenv

load_dotenv()


def empty_chromadb():
    """Delete all collections from ChromaDB"""
    
    print("=" * 60)
    print("ChromaDB Collection Deleter")
    print("=" * 60)
    
    try:
        # Connect to ChromaDB
        print(f"\n🔌 Connecting to ChromaDB at {settings.CHROMA_HOST}:{settings.CHROMA_PORT}...")
        client = chromadb.HttpClient(
            host=settings.CHROMA_HOST,
            port=settings.CHROMA_PORT
        )
        
        # Test connection
        client.heartbeat()
        print("✅ Connected successfully!\n")
        
    except Exception as e:
        print(f"❌ Failed to connect to ChromaDB: {e}")
        print(f"\n💡 Make sure ChromaDB is running:")
        print(f"   docker run -d -p {settings.CHROMA_PORT}:{settings.CHROMA_PORT} chromadb/chroma")
        return
    
    # Get all collections
    collections = client.list_collections()
    
    if not collections:
        print("📦 No collections found - database is already empty!")
        return
    
    print(f"Found {len(collections)} collection(s):\n")
    for collection in collections:
        print(f"  • {collection.name}")
    
    # Confirm deletion
    confirm = input("\n⚠️  Delete ALL collections? (yes/no): ")
    if confirm.lower() != 'yes':
        print("❌ Cancelled - no collections deleted")
        return
    
    # Delete each collection
    print()
    for collection in collections:
        try:
            print(f"🗑️  Deleting collection: {collection.name}")
            client.delete_collection(collection.name)
            print(f"   ✅ Deleted successfully")
        except Exception as e:
            print(f"   ❌ Error deleting {collection.name}: {e}")
    
    print("\n✅ All ChromaDB collections deleted!")


if __name__ == "__main__":
    empty_chromadb()