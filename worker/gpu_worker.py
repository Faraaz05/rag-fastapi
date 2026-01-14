"""
GPU Worker for Document Processing
Uses Unstructured.io for hi_res PDF partitioning (GPU-accelerated)
Follows the exact logic from 8_multi_modal_rag.ipynb
"""
import json
import logging
import sys
import os
from pathlib import Path
from typing import List, Dict
import time

import redis
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from dotenv import load_dotenv

# Unstructured for document parsing
from unstructured.partition.pdf import partition_pdf
from unstructured.chunking.title import chunk_by_title

# LangChain components
from langchain_core.documents import Document
from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage
from langchain_google_genai import GoogleGenerativeAIEmbeddings
import chromadb

# Import project models
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.models import File, FileStatus
from app.core.config import settings

# Load environment
load_dotenv()

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(name)s | %(levelname)s | %(message)s',
    datefmt='%H:%M:%S'
)
log = logging.getLogger("GPUWorker")

# Database connection
engine = create_engine(settings.DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Redis connection
redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)

# Groq LLM for AI-enhanced summaries
llm = ChatGroq(
    model_name="meta-llama/llama-4-scout-17b-16e-instruct",
    temperature=0,
    max_tokens=4096
)


def partition_document(file_path: str):
    """Extract elements from PDF using unstructured - EXACT LOGIC FROM NOTEBOOK"""
    log.info(f"📄 Partitioning document: {file_path}")
    
    elements = partition_pdf(
        filename=file_path,
        strategy="hi_res",  # GPU-accelerated processing
        infer_table_structure=True,
        extract_image_block_types=["Image"],
        extract_image_block_to_payload=True
    )
    
    log.info(f"✅ Extracted {len(elements)} elements")
    return elements


def create_chunks_by_title(elements):
    """Create intelligent chunks using title-based strategy - EXACT LOGIC FROM NOTEBOOK"""
    log.info("🔨 Creating smart chunks...")
    
    chunks = chunk_by_title(
        elements,
        max_characters=3000,
        new_after_n_chars=2400,
        combine_text_under_n_chars=500
    )
    
    log.info(f"✅ Created {len(chunks)} chunks")
    return chunks


def create_ai_enhanced_summary(text: str, tables: List[str], images: List[str]) -> str:
    """Create AI-enhanced summary using Llama 4 Scout - EXACT LOGIC FROM NOTEBOOK"""
    try:
        prompt_text = f"""You are an expert document indexer. Analyze the content below.
        
[TEXT CONTENT]
{text}
"""
        if tables:
            prompt_text += "\n[TABULAR DATA]\n" + "\n".join(tables)
            
        prompt_text += """
[TASK]
Generate a highly searchable description including:
1. Core technical facts and data points.
2. Visual patterns or diagrams observed.
3. Summary of topics for vector retrieval.
"""

        message_content = [{"type": "text", "text": prompt_text}]
        
        # Add images (max 5 per request)
        for img_b64 in images[:5]:
            message_content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}
            })
        
        response = llm.invoke([HumanMessage(content=message_content)])
        return response.content
        
    except Exception as e:
        log.error(f"AI Summary Failed: {str(e)}")
        return f"{text[:300]}... [Summary Fallback]"


def separate_content_types(chunk) -> Dict[str, List]:
    """Extract text, tables, and images from chunk - EXACT LOGIC FROM NOTEBOOK"""
    text_parts = []
    tables = []
    images = []
    
    if hasattr(chunk.metadata, 'orig_elements'):
        for element in chunk.metadata.orig_elements:
            elem_dict = element.to_dict()
            
            # Extract text content
            if elem_dict.get('type') in ['NarrativeText', 'Title', 'ListItem', 'Text']:
                text_parts.append(elem_dict.get('text', ''))
            
            # Extract tables (HTML format)
            elif elem_dict.get('type') == 'Table':
                table_html = elem_dict.get('metadata', {}).get('text_as_html', '')
                if table_html:
                    tables.append(table_html)
            
            # Extract images (base64)
            elif elem_dict.get('type') == 'Image':
                img_b64 = elem_dict.get('metadata', {}).get('image_base64', '')
                if img_b64:
                    images.append(img_b64)
    else:
        text_parts.append(str(chunk))
    
    return {
        'text': '\n\n'.join(text_parts),
        'tables': tables,
        'images': images
    }


def summarise_chunks(chunks: List, document_name: str) -> List[Document]:
    """Process all chunks with AI enhancement - EXACT LOGIC FROM NOTEBOOK"""
    log.info(f"🚀 Starting LPU processing for {len(chunks)} chunks")
    
    langchain_documents = []
    total = len(chunks)
    
    for i, chunk in enumerate(chunks):
        curr = i + 1
        log.info(f"📦 Processing Chunk [{curr}/{total}]")
        
        positions = []
        if hasattr(chunk.metadata, 'orig_elements'):
            for elem in chunk.metadata.orig_elements:
                elem_dict = elem.to_dict()
                
                # Extract the page number for THIS specific element
                elem_page = elem_dict.get('metadata', {}).get('page_number')
                
                if 'coordinates' in elem_dict.get('metadata', {}):
                    coords = elem_dict['metadata']['coordinates']
                    positions.append({
                        'type': elem_dict.get('type'),
                        'page_number': elem_page,  # Include page number for each element
                        'coordinates': {
                            'points': [[float(x), float(y)] for x, y in coords['points']],
                            'system': coords['system'],
                            'layout_width': int(coords['layout_width']),
                            'layout_height': int(coords['layout_height'])
                        }
                    })

        page_num = chunk.metadata.page_number if hasattr(chunk.metadata, 'page_number') else None

        # Analyze content
        content_data = separate_content_types(chunk)
        
        has_complex = len(content_data['tables']) > 0 or len(content_data['images']) > 0
        
        if has_complex:
            log.info(f"   ∟ 👁️ Vision detected ({len(content_data['images'])} images, {len(content_data['tables'])} tables)")
            summary = create_ai_enhanced_summary(
                content_data['text'], 
                content_data['tables'], 
                content_data['images']
            )
            log.info(f"   ∟ ✅ AI Summary generated ({len(summary.split())} words)")
        else:
            log.info("   ∟ 📝 Plain text chunk, skipping AI vision")
            summary = content_data['text']
        
        # Create LangChain document
        doc = Document(
            page_content=summary,
            metadata={
                "source_type": "document",
                "document_name": document_name,
                "original_content": json.dumps({
                    "raw_text": content_data['text'],
                    "tables_html": content_data['tables'],
                    "images_base64": content_data['images']
                }),
                "page_number": page_num,
                "chunk_index": i + 1,
                "positions": json.dumps(positions),
                "has_vision_data": has_complex
            }
        )
        langchain_documents.append(doc)
    
    log.info(f"✨ Successfully processed {len(langchain_documents)} documents")
    return langchain_documents


def export_chunks_to_json(chunks, filename):
    """Export processed chunks to JSON - EXACT LOGIC FROM NOTEBOOK"""
    export_data = []
    
    for i, doc in enumerate(chunks):
        original_content = json.loads(doc.metadata.get("original_content", "{}"))
        positions_str = doc.metadata.get("positions", "[]")
        positions = json.loads(positions_str) if isinstance(positions_str, str) else positions_str
        
        chunk_data = {
            "chunk_id": i + 1,
            "enhanced_content": doc.page_content,
            "metadata": {
                "source_type": doc.metadata.get("source_type", "document"),
                "document_name": doc.metadata.get("document_name"),
                "page_number": doc.metadata.get("page_number", "N/A"),
                "chunk_index": doc.metadata.get("chunk_index", i + 1),
                "positions": positions,
                "original_content": original_content,
                "has_tables": len(original_content.get("tables_html", [])) > 0,
                "has_images": len(original_content.get("images_base64", [])) > 0
            }
        }
        export_data.append(chunk_data)
    
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(export_data, f, indent=2, ensure_ascii=False)
    
    log.info(f"✅ Exported {len(export_data)} chunks to {filename}")
    return export_data


def sanitize_metadata(metadata: dict) -> dict:
    """
    Sanitize metadata to ensure ChromaDB compatibility.
    ChromaDB only accepts strings, ints, floats, and bools.
    """
    sanitized = {}
    for key, value in metadata.items():
        if isinstance(value, (str, int, float, bool)):
            sanitized[key] = value
        elif value is None:
            sanitized[key] = ""
        else:
            # Convert complex objects to JSON strings
            sanitized[key] = json.dumps(value) if not isinstance(value, str) else str(value)
    return sanitized


def process_document(message: dict, db: Session):
    """Main document processing function with full pipeline"""
    project_id = message["project_id"]
    file_id = message["file_id"]
    file_path = message["file_path"]
    original_filename = message["original_filename"]
    
    log.info(f"🎯 Starting processing for file: {original_filename}")
    
    # Get file record from database
    db_file = db.query(File).filter(File.file_id == file_id).first()
    if not db_file:
        log.error(f"❌ File record not found: {file_id}")
        return
    
    try:
        # ========== STAGE 1: PARTITIONING ==========
        log.info("📋 STAGE 1: PARTITIONING")
        db_file.status = FileStatus.PARTITIONING
        db.commit()
        log.info("📊 Status updated to PARTITIONING")
        
        # Step 1: Partition document
        elements = partition_document(file_path)
        
        # Step 2: Create chunks
        chunks = create_chunks_by_title(elements)
        
        # Step 3: AI Summarization
        processed_chunks = summarise_chunks(chunks, original_filename)
        
        # Step 4: Save to JSON (for backup/debugging)
        processed_dir = Path(settings.UPLOAD_DIR.replace("raw", "processed")) / str(project_id)
        processed_dir.mkdir(parents=True, exist_ok=True)
        
        output_file = processed_dir / f"{file_id}.json"
        export_chunks_to_json(processed_chunks, str(output_file))
        db_file.processed_path = str(output_file)
        
        # ========== STAGE 2: EMBEDDING ==========
        log.info("\n🔮 STAGE 2: EMBEDDING")
        db_file.status = FileStatus.EMBEDDING
        db.commit()
        log.info("📊 Status updated to EMBEDDING")
        
        # Initialize Gemini Embedding model (from notebook logic)
        log.info("🔮 Creating embeddings via Google Gemini API")
        embedding_model = GoogleGenerativeAIEmbeddings(
            model="models/text-embedding-004",
            task_type="retrieval_document"
        )
        
        # Generate embeddings for all chunks
        log.info(f"📝 Generating embeddings for {len(processed_chunks)} chunks...")
        texts = [doc.page_content for doc in processed_chunks]
        embeddings = embedding_model.embed_documents(texts)
        log.info(f"✅ Generated {len(embeddings)} embeddings")
        
        # ========== STAGE 3: INDEXING ==========
        log.info("\n💾 STAGE 3: INDEXING")
        db_file.status = FileStatus.INDEXING
        db.commit()
        log.info("📊 Status updated to INDEXING")
        
        # Connect to ChromaDB via HTTP
        log.info(f"🔌 Connecting to ChromaDB at {settings.CHROMA_HOST}:{settings.CHROMA_PORT}")
        chroma_client = chromadb.HttpClient(
            host=settings.CHROMA_HOST,
            port=settings.CHROMA_PORT
        )
        
        # Test connection
        try:
            chroma_client.heartbeat()
            log.info("✅ ChromaDB connection successful")
        except Exception as e:
            raise ConnectionError(f"Failed to connect to ChromaDB: {str(e)}")
        
        # Generate collection name (project-specific)
        collection_name = f"project_{project_id}"
        
        log.info(f"--- Collection: {collection_name} ---")
        
        # Get or create collection
        try:
            collection = chroma_client.get_or_create_collection(
                name=collection_name,
                metadata={"hnsw:space": "cosine"}
            )
            existing_count = collection.count()
            log.info(f"📊 Collection has {existing_count} existing chunks")
        except Exception as e:
            raise RuntimeError(f"Failed to get/create collection: {str(e)}")
        
        # Prepare data for ChromaDB
        ids = [f"{file_id}_chunk_{i}" for i in range(len(processed_chunks))]
        documents = [doc.page_content for doc in processed_chunks]
        
        # Sanitize metadata for ChromaDB compatibility
        log.info("🧹 Sanitizing metadata for ChromaDB...")
        metadatas = []
        for doc in processed_chunks:
            sanitized_meta = sanitize_metadata(doc.metadata)
            metadatas.append(sanitized_meta)
        
        # Add chunks to ChromaDB
        log.info(f"📤 Adding {len(ids)} chunks to ChromaDB...")
        try:
            collection.add(
                ids=ids,
                embeddings=embeddings,
                documents=documents,
                metadatas=metadatas
            )
            log.info("✅ Chunks successfully added to ChromaDB")
        except Exception as e:
            raise RuntimeError(f"Failed to add chunks to ChromaDB: {str(e)}")
        
        # Verify final state
        final_count = collection.count()
        log.info(f"\n✅ Vector store updated successfully!")
        log.info(f"📊 Collection '{collection_name}' now contains: {final_count} chunks")
        log.info(f"   Added {len(ids)} new chunks from this document")
        
        # ========== STAGE 4: COMPLETED ==========
        log.info("\n🎉 STAGE 4: COMPLETED")
        db_file.status = FileStatus.COMPLETED
        db.commit()
        
        log.info(f"✅ Processing completed successfully for {original_filename}")
        log.info(f"📄 Processed {len(processed_chunks)} chunks")
        log.info(f"💾 Stored in ChromaDB collection: {collection_name}")
        
    except Exception as e:
        log.error(f"❌ Processing failed: {str(e)}", exc_info=True)
        db_file.status = FileStatus.FAILED
        db_file.error_message = str(e)[:500]  # Limit error message length
        db.commit()


def main():
    """Main worker loop"""
    log.info("🚀 GPU Worker started. Waiting for tasks...")
    log.info(f"📡 Connected to Redis: {settings.REDIS_URL}")
    log.info(f"💾 Connected to Database: {settings.DATABASE_URL}")
    log.info(f"📂 Upload directory: {settings.UPLOAD_DIR}")
    
    queue_name = "ingestion_queue"
    
    while True:
        try:
            # Block and wait for a message (timeout: 1 second)
            result = redis_client.brpop(queue_name, timeout=1)
            
            if result:
                _, message_json = result
                message = json.loads(message_json)
                
                log.info(f"\n{'='*60}")
                log.info(f"📨 New task received: {message.get('original_filename')}")
                log.info(f"{'='*60}\n")
                
                # Get database session
                db = SessionLocal()
                try:
                    process_document(message, db)
                finally:
                    db.close()
            
        except KeyboardInterrupt:
            log.info("\n⚠️  Worker stopped by user")
            break
        except Exception as e:
            log.error(f"❌ Worker error: {str(e)}", exc_info=True)
            time.sleep(5)  # Wait before retrying


if __name__ == "__main__":
    main()
