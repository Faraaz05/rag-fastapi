#!/usr/bin/env python3
"""
ChromaDB Collection Inspector
Lists all collections and their content in ChromaDB
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


def inspect_chromadb():
    """Inspect ChromaDB collections and content"""
    
    print("=" * 60)
    print("ChromaDB Collection Inspector")
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
    
    # List all collections
    try:
        collections = client.list_collections()
        
        if not collections:
            print("📦 No collections found in ChromaDB")
            return
        
        print(f"📊 Found {len(collections)} collection(s):\n")
        
        for collection in collections:
            print("─" * 60)
            print(f"📁 Collection: {collection.name}")
            print(f"   Metadata: {collection.metadata}")
            
            # Get collection details
            count = collection.count()
            print(f"   Total chunks: {count}")
            
            if count > 0:
                # Get sample data
                results = collection.get(
                    limit=5,
                    include=['metadatas', 'documents']
                )
                
                # Analyze metadata
                if results['metadatas']:
                    # Count by source type
                    source_types = {}
                    documents_list = {}
                    
                    for meta in results['metadatas']:
                        source_type = meta.get('source_type', 'unknown')
                        source_types[source_type] = source_types.get(source_type, 0) + 1
                        
                        doc_name = meta.get('document_name', 'unknown')
                        documents_list[doc_name] = documents_list.get(doc_name, 0) + 1
                    
                    print(f"\n   📋 Content breakdown:")
                    for source_type, count in source_types.items():
                        print(f"      • {source_type}: {count} samples shown")
                    
                    print(f"\n   📄 Documents found:")
                    for doc_name, count in documents_list.items():
                        print(f"      • {doc_name}: {count} samples shown")
                    
                    # Show sample metadata keys
                    if results['metadatas'][0]:
                        sample_keys = list(results['metadatas'][0].keys())
                        print(f"\n   🔑 Sample metadata keys:")
                        print(f"      {', '.join(sample_keys[:10])}")
                        if len(sample_keys) > 10:
                            print(f"      ... and {len(sample_keys) - 10} more")
                    
                    # Show first chunk preview
                    if results['documents']:
                        first_doc = results['documents'][0]
                        preview = first_doc[:200] + "..." if len(first_doc) > 200 else first_doc
                        print(f"\n   📝 First chunk preview:")
                        print(f"      {preview}")
            
            print()
        
        print("─" * 60)
        print(f"\n✅ Inspection complete!")
        
    except Exception as e:
        print(f"❌ Error inspecting collections: {e}")
        import traceback
        traceback.print_exc()


def view_collection_details(collection_name: str):
    """View detailed information about a specific collection"""
    
    print("=" * 60)
    print(f"Collection Details: {collection_name}")
    print("=" * 60)
    
    try:
        # Connect to ChromaDB
        client = chromadb.HttpClient(
            host=settings.CHROMA_HOST,
            port=settings.CHROMA_PORT
        )
        
        collection = client.get_collection(name=collection_name)
        
        # Get all data
        results = collection.get(
            include=['metadatas', 'documents']
        )
        
        total_chunks = len(results['ids'])
        print(f"\n📊 Total chunks: {total_chunks}\n")
        
        # Show all chunks
        for i, (id, doc, meta) in enumerate(zip(results['ids'], results['documents'], results['metadatas'])):
            print(f"Chunk {i+1}/{total_chunks}")
            print(f"  ID: {id}")
            print(f"  Document: {meta.get('document_name', 'N/A')}")
            print(f"  Page: {meta.get('page_number', 'N/A')}")
            print(f"  Source Type: {meta.get('source_type', 'N/A')}")
            
            preview = doc[:150] + "..." if len(doc) > 150 else doc
            print(f"  Content: {preview}")
            print()
        
    except Exception as e:
        print(f"❌ Error: {e}")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="ChromaDB Collection Inspector")
    parser.add_argument(
        '--collection',
        type=str,
        help='View details for a specific collection (e.g., project_1)'
    )
    
    args = parser.parse_args()
    
    if args.collection:
        view_collection_details(args.collection)
    else:
        inspect_chromadb()
