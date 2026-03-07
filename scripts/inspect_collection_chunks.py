#!/usr/bin/env python3
"""
ChromaDB Collection Chunk Inspector
Displays all chunks in a collection with full details including metadata and content.
"""
import sys
import os
from pathlib import Path
import json
from datetime import datetime

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import chromadb
from app.core.config import settings
from dotenv import load_dotenv

load_dotenv()


def inspect_all_chunks(collection_name: str, show_full_content: bool = False, export_json: str = None):
    """
    Inspect all chunks in a ChromaDB collection with full details.
    
    Args:
        collection_name: Name of the collection (e.g., 'project_1')
        show_full_content: If True, show full chunk content instead of preview
        export_json: If provided, export results to JSON file
    """
    
    print("=" * 80)
    print(f"ChromaDB Collection Chunk Inspector: {collection_name}")
    print("=" * 80)
    
    try:
        # Connect to ChromaDB
        print(f"\n🔌 Connecting to ChromaDB at {settings.CHROMA_HOST}:{settings.CHROMA_PORT}...")
        client = chromadb.HttpClient(
            host="localhost",
            port=8000
        )
        
        # Test connection
        client.heartbeat()
        print("✅ Connected successfully!\n")
        
    except Exception as e:
        print(f"❌ Failed to connect to ChromaDB: {e}")
        print(f"\n💡 Make sure ChromaDB is running")
        return
    
    try:
        # Get collection
        collection = client.get_collection(name=collection_name)
        print(f"📁 Collection: {collection_name}")
        print(f"   Metadata: {collection.metadata}")
        
        # Get total count
        total_chunks = collection.count()
        print(f"   Total chunks: {total_chunks}\n")
        
        if total_chunks == 0:
            print("📦 No chunks found in this collection")
            return
        
        # Get all chunks
        print(f"🔍 Fetching all {total_chunks} chunks...\n")
        results = collection.get(
            include=['metadatas', 'documents', 'embeddings']
        )
        
        # Analyze content
        source_types = {}
        documents = {}
        meetings = {}
        
        for meta in results['metadatas']:
            # Count source types
            source_type = meta.get('source_type', 'unknown')
            source_types[source_type] = source_types.get(source_type, 0) + 1
            
            # Count documents
            if source_type == 'document':
                doc_name = meta.get('document_name', 'unknown')
                documents[doc_name] = documents.get(doc_name, 0) + 1
            
            # Count meeting transcripts
            elif source_type == 'meeting_transcript':
                meeting_name = meta.get('meeting_name', 'unknown')
                meetings[meeting_name] = meetings.get(meeting_name, 0) + 1
        
        # Display summary
        print("=" * 80)
        print("📊 COLLECTION SUMMARY")
        print("=" * 80)
        print(f"\n📈 Source Type Distribution:")
        for source_type, count in sorted(source_types.items()):
            percentage = (count / total_chunks) * 100
            print(f"   • {source_type}: {count} chunks ({percentage:.1f}%)")
        
        if documents:
            print(f"\n📄 Documents ({len(documents)} unique):")
            for doc_name, count in sorted(documents.items()):
                print(f"   • {doc_name}: {count} chunks")
        
        if meetings:
            print(f"\n🎙️  Meeting Transcripts ({len(meetings)} unique):")
            for meeting_name, count in sorted(meetings.items()):
                print(f"   • {meeting_name}: {count} chunks")
        
        # Display all chunks
        print("\n" + "=" * 80)
        print("📋 ALL CHUNKS DETAILS")
        print("=" * 80 + "\n")
        
        chunk_data = []
        
        for i, (chunk_id, doc, meta) in enumerate(zip(results['ids'], results['documents'], results['metadatas'])):
            chunk_info = {
                "index": i + 1,
                "id": chunk_id,
                "metadata": meta,
                "content": doc
            }
            chunk_data.append(chunk_info)
            
            print(f"┌─ Chunk {i+1}/{total_chunks} {'─' * (70 - len(str(i+1)) - len(str(total_chunks)))}")
            print(f"│ ID: {chunk_id}")
            print(f"│")
            print(f"│ 📋 Metadata:")
            for key, value in meta.items():
                # Format value nicely
                if isinstance(value, (list, dict)):
                    value_str = json.dumps(value)
                else:
                    value_str = str(value)
                
                # Truncate long values
                if len(value_str) > 80:
                    value_str = value_str[:77] + "..."
                
                print(f"│    • {key}: {value_str}")
            
            print(f"│")
            print(f"│ 📝 Content ({len(doc)} chars):")
            
            if show_full_content:
                # Show full content with line breaks
                lines = doc.split('\n')
                for line in lines:
                    print(f"│    {line}")
            else:
                # Show preview (first 300 chars)
                preview = doc[:300].replace('\n', '\n│    ')
                print(f"│    {preview}")
                if len(doc) > 300:
                    print(f"│    ... ({len(doc) - 300} more characters)")
            
            print(f"└{'─' * 78}\n")
        
        # Export to JSON if requested
        if export_json:
            export_data = {
                "collection_name": collection_name,
                "total_chunks": total_chunks,
                "exported_at": datetime.utcnow().isoformat(),
                "summary": {
                    "source_types": source_types,
                    "documents": documents,
                    "meetings": meetings
                },
                "chunks": chunk_data
            }
            
            with open(export_json, 'w', encoding='utf-8') as f:
                json.dump(export_data, f, indent=2, ensure_ascii=False)
            
            print(f"💾 Exported to: {export_json}\n")
        
        print("=" * 80)
        print(f"✅ Inspection complete! Displayed {total_chunks} chunks")
        print("=" * 80)
        
    except Exception as e:
        print(f"❌ Error inspecting collection: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Inspect all chunks in a ChromaDB collection",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # View all chunks in project_1 collection (preview mode)
  python scripts/inspect_collection_chunks.py project_1
  
  # View all chunks with full content
  python scripts/inspect_collection_chunks.py project_1 --full
  
  # Export chunks to JSON file
  python scripts/inspect_collection_chunks.py project_1 --export output.json
  
  # Full content + export
  python scripts/inspect_collection_chunks.py project_1 --full --export chunks.json
        """
    )
    
    parser.add_argument(
        'collection',
        type=str,
        help='Collection name (e.g., project_1, project_2)'
    )
    
    parser.add_argument(
        '--full',
        action='store_true',
        help='Show full content instead of preview'
    )
    
    parser.add_argument(
        '--export',
        type=str,
        metavar='FILE',
        help='Export chunks to JSON file'
    )
    
    args = parser.parse_args()
    
    inspect_all_chunks(
        collection_name=args.collection,
        show_full_content=args.full,
        export_json=args.export
    )
