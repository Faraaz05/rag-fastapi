"""
AWS Batch GPU Worker for Vector Trace
Processes a single document and exits.
"""
import json
import logging
import sys
import os
import subprocess
import tempfile
import shutil
from pathlib import Path
from typing import List, Dict

from dotenv import load_dotenv
load_dotenv('/app/.env')

# Database & Models
from sqlalchemy import create_engine, Column, Integer, String, Enum
from sqlalchemy.orm import sessionmaker, Session, declarative_base
import enum

# Document Processing
from unstructured.partition.pdf import partition_pdf
from unstructured.chunking.title import chunk_by_title
from langchain_core.documents import Document
from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage
from langchain_google_genai import GoogleGenerativeAIEmbeddings
import chromadb

# --- MINIMAL MODELS (Bridge to your DB without copying the app) ---
Base = declarative_base()

class FileStatus(str, enum.Enum):
    QUEUED = "QUEUED"
    PARTITIONING = "PARTITIONING"
    EMBEDDING = "EMBEDDING"
    INDEXING = "INDEXING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"

class File(Base):
    __tablename__ = "files"
    file_id = Column(String, primary_key=True)
    project_id = Column(Integer)
    original_filename = Column(String)
    file_path = Column(String)
    status = Column(String)  # Simple string for DB compatibility
    processed_path = Column(String)
    error_message = Column(String)

def convert_docx_to_pdf(docx_path: str) -> str:
    """Convert DOCX to PDF using LibreOffice."""
    import tempfile
    import shutil
    from pathlib import Path
    
    temp_dir = tempfile.mkdtemp()
    try:
        pdf_path = docx_path.replace('.docx', '.pdf')
        log.info(f"🔄 Running LibreOffice conversion...")
        
        cmd = [
            'libreoffice',
            '--headless',
            '--convert-to', 'pdf',
            '--outdir', temp_dir,
            docx_path
        ]
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120  # 2 minute timeout
        )
        
        if result.returncode != 0:
            raise RuntimeError(f"LibreOffice conversion failed: {result.stderr}")
        
        # Find the generated PDF file
        docx_filename = Path(docx_path).stem
        temp_pdf_path = Path(temp_dir) / f"{docx_filename}.pdf"
        
        if not temp_pdf_path.exists():
            raise RuntimeError(f"PDF file not generated: {temp_pdf_path}")
        
        # Move the PDF to the same directory as the DOCX
        final_pdf_path = Path(docx_path).parent / f"{docx_filename}.pdf"
        shutil.move(str(temp_pdf_path), str(final_pdf_path))
        
        log.info(f"✅ Conversion successful: {final_pdf_path}")
        return str(final_pdf_path)
        
    except subprocess.TimeoutExpired:
        raise RuntimeError("LibreOffice conversion timed out (exceeded 2 minutes)")
    except Exception as e:
        raise RuntimeError(f"DOCX to PDF conversion failed: {str(e)}")
    finally:
        # Clean up temporary directory
        shutil.rmtree(temp_dir, ignore_errors=True)


def partition_document(file_path: str):
    """Extract elements from PDF using unstructured."""
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
    """Create intelligent chunks using title-based strategy."""
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
    """Create AI-enhanced summary using Llama 4 Scout."""
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
    """Extract text, tables, and images from chunk."""
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
    """Process all chunks with AI enhancement."""
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
                        'page_number': elem_page,
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


def export_chunks_to_json(chunks, project_id, file_id, bucket_name):
    """Export processed chunks to JSON in S3 - EXACT LOGIC FROM GPU WORKER"""
    import boto3
    
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
    
    # Save to S3
    s3_key = f"projects/{project_id}/processed/{file_id}.json"
    json_content = json.dumps(export_data, indent=2, ensure_ascii=False)
    json_bytes = json_content.encode('utf-8')
    
    s3 = boto3.client('s3')
    try:
        s3.put_object(
            Bucket=bucket_name,
            Key=s3_key,
            Body=json_bytes,
            ContentType='application/json'
        )
        log.info(f"✅ Exported {len(export_data)} chunks to s3://{bucket_name}/{s3_key}")
        return s3_key
    except Exception as e:
        log.error(f"Failed to save chunks to S3: {e}")
        return None


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

# --- CONFIG & LOGGING ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')
log = logging.getLogger("BatchWorker")

# Load DB URL from Env (Passed by Batch/Task Definition)
DATABASE_URL = os.getenv("DATABASE_URL")
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)

# Initialize LLM
llm = ChatGroq(
    model_name="meta-llama/llama-4-scout-17b-16e-instruct",
    temperature=0,
    max_tokens=4096,
    groq_api_key=os.getenv("GROQ_API_KEY")
)

# (All your helper functions: convert_docx_to_pdf, partition_document, 
# separate_content_types, create_ai_enhanced_summary stay exactly the same as your local script)

def process_document_single():
    """Execution logic for a single AWS Batch Job"""
    # 1. Get Task Metadata from Environment
    project_id = os.getenv("PROJECT_ID")
    file_id = os.getenv("FILE_ID")
    s3_key = os.getenv("S3_PATH") # e.g., 'uploads/1/doc.pdf'
    original_filename = os.getenv("ORIGINAL_FILENAME")
    bucket_name = os.getenv("S3_BUCKET_NAME")

    if not all([project_id, file_id, s3_key]):
        log.error("❌ Missing required environment variables.")
        sys.exit(1)

    db: Session = SessionLocal()
    
    # Query the file record first
    db_file = db.query(File).filter(File.file_id == file_id).first()
    
    try:
        # Download from S3 logic
        import boto3
        s3 = boto3.client('s3')
        temp_dir = tempfile.mkdtemp()
        local_input_path = os.path.join(temp_dir, original_filename)
        
        log.info(f"📥 Downloading s3://{bucket_name}/{s3_key}")
        s3.download_file(bucket_name, s3_key, local_input_path)

        # Update DB Status
        if db_file:
            db_file.status = FileStatus.PARTITIONING
            db.commit()

        # --- EXECUTE PIPELINE ---
        # 1. Conversion if DOCX
        actual_path = local_input_path
        if original_filename.lower().endswith('.docx'):
            actual_path = convert_docx_to_pdf(local_input_path)

        # 2. Unstructured Partition
        elements = partition_document(actual_path)
        chunks = chunk_by_title(elements, max_characters=3000)
        processed_chunks = summarise_chunks(chunks, original_filename)

        # 3. Export chunks to JSON in S3
        log.info("📄 Exporting chunks to JSON...")
        processed_path = export_chunks_to_json(processed_chunks, project_id, file_id, bucket_name)
        if processed_path and db_file:
            db_file.processed_path = processed_path
            db.commit()

        # 4. Embedding
        db_file.status = FileStatus.EMBEDDING
        db.commit()
        embedding_model = GoogleGenerativeAIEmbeddings(model="models/text-embedding-004")
        texts = [doc.page_content for doc in processed_chunks]
        embeddings = embedding_model.embed_documents(texts)

        # 5. ChromaDB Indexing
        db_file.status = FileStatus.INDEXING
        db.commit()
        chroma_client = chromadb.HttpClient(host=os.getenv("CHROMA_HOST"), port=os.getenv("CHROMA_PORT"))
        collection = chroma_client.get_or_create_collection(name=f"project_{project_id}")
        
        ids = [f"{file_id}_chunk_{i}" for i in range(len(processed_chunks))]
        metadatas = [sanitize_metadata(doc.metadata) for doc in processed_chunks]
        
        collection.add(ids=ids, embeddings=embeddings, documents=texts, metadatas=metadatas)

        # Finalize
        db_file.status = FileStatus.COMPLETED
        db.commit()
        log.info("🎉 Job Finished Successfully")

    except Exception as e:
        log.error(f"❌ Job Failed: {str(e)}")
        if db_file:
            db_file.status = FileStatus.FAILED
            db_file.error_message = str(e)
            db.commit()
        sys.exit(1)
    finally:
        db.close()
        shutil.rmtree(temp_dir, ignore_errors=True)

if __name__ == "__main__":
    process_document_single()