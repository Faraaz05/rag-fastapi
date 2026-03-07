"""
RAG service for unified query pipeline.
Ports logic from unified_query_pipeline.ipynb for FastAPI integration.
"""
import json
import re
import logging
import traceback
from typing import List, Dict, Optional, AsyncGenerator
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_chroma import Chroma
from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
import chromadb
from ..core.config import settings

# Configure logger
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


def query_with_filter(
    question: str,
    project_id: int,
    top_k: int = 5,
    filter_type: str = "unified"
) -> List[Dict]:
    """
    Query ChromaDB with optional source type filtering.
    
    Args:
        question: User's query
        project_id: Project ID for collection
        top_k: Number of results to retrieve
        filter_type: "unified", "document", or "transcript"
        
    Returns:
        List of retrieved chunks with metadata
    """
    collection_name = f"project_{project_id}"
    logger.info(f"🔍 Starting query_with_filter for collection: {collection_name}")
    logger.info(f"   Question: {question[:100]}...")
    logger.info(f"   Filter: {filter_type}, Top K: {top_k}")
    
    try:
        # Step 1: Connect to ChromaDB
        logger.info(f"📡 Connecting to ChromaDB at {settings.CHROMA_HOST}:{settings.CHROMA_PORT}")
        chroma_client = chromadb.HttpClient(
            host=settings.CHROMA_HOST,
            port=settings.CHROMA_PORT
        )
        logger.info("✅ ChromaDB HttpClient created successfully")
        
        # Step 2: Test connection
        try:
            heartbeat = chroma_client.heartbeat()
            logger.info(f"✅ ChromaDB heartbeat: {heartbeat}")
        except Exception as conn_e:
            logger.error(f"❌ ChromaDB connection test failed: {conn_e}")
            logger.error(traceback.format_exc())
            raise
        
        # Step 3: Verify collection exists
        try:
            collections = chroma_client.list_collections()
            collection_names = [c.name for c in collections]
            logger.info(f"📋 Available collections: {collection_names}")
            
            if collection_name not in collection_names:
                logger.error(f"❌ Collection '{collection_name}' not found!")
                raise ValueError(f"Collection '{collection_name}' does not exist")
            
            logger.info(f"✅ Collection '{collection_name}' exists")
        except Exception as coll_e:
            logger.error(f"❌ Collection verification failed: {coll_e}")
            logger.error(traceback.format_exc())
            raise
        
        # Step 4: Initialize embedding model
        logger.info("🧮 Initializing GoogleGenerativeAIEmbeddings...")
        try:
            embedding_model = GoogleGenerativeAIEmbeddings(
                model="models/gemini-embedding-001",
                task_type="retrieval_query"
            )
            logger.info("✅ GoogleGenerativeAIEmbeddings initialized successfully")
        except Exception as emb_e:
            logger.error(f"❌ Embedding model initialization failed: {emb_e}")
            logger.error("   This usually means GOOGLE_API_KEY is missing or invalid")
            logger.error(traceback.format_exc())
            raise
        
        # Step 5: Create LangChain Chroma wrapper
        logger.info("🔗 Creating LangChain Chroma vectorstore wrapper...")
        try:
            vectorstore = Chroma(
                client=chroma_client,
                collection_name=collection_name,
                embedding_function=embedding_model
            )
            logger.info("✅ Vectorstore wrapper created successfully")
        except Exception as vs_e:
            logger.error(f"❌ Vectorstore creation failed: {vs_e}")
            logger.error(traceback.format_exc())
            raise
        
        # Step 6: Build search kwargs and apply filters
        search_kwargs = {"k": top_k}
        
        if filter_type == "document":
            search_kwargs["filter"] = {"source_type": "document"}
            logger.info("📄 Filter applied: documents only")
        elif filter_type == "transcript":
            search_kwargs["filter"] = {"source_type": "meeting_transcript"}
            logger.info("🎤 Filter applied: transcripts only")
        else:
            logger.info("🌐 No filter applied: unified search")
        
        # Step 7: Create retriever and execute query
        logger.info("🔎 Creating retriever and executing query...")
        try:
            retriever = vectorstore.as_retriever(search_kwargs=search_kwargs)
            logger.info("✅ Retriever created")
            
            retrieved_chunks = retriever.invoke(question)
            logger.info(f"✅ Query executed successfully! Retrieved {len(retrieved_chunks)} chunks")
            
            # Log sample metadata from first chunk
            if retrieved_chunks:
                first_chunk = retrieved_chunks[0]
                logger.info(f"   First chunk metadata: {first_chunk.metadata}")
                logger.info(f"   First chunk content preview: {first_chunk.page_content[:100]}...")
            
            return retrieved_chunks
            
        except Exception as query_e:
            logger.error(f"❌ Query execution failed: {query_e}")
            logger.error(traceback.format_exc())
            raise
        
    except Exception as e:
        logger.error(f"❌ query_with_filter failed with error: {e}")
        logger.error(f"   Error type: {type(e).__name__}")
        logger.error(f"   Full traceback:\n{traceback.format_exc()}")
        raise  # Re-raise to let the endpoint handler catch it


def format_answer_with_citations(answer_text: str, chunks_metadata: Dict) -> str:
    """
    Replace [CITE:X] with appropriate format for documents and transcripts.
    
    Documents: [doc_name(p.X)]
    Transcripts: [meeting_name@timestamp]
    """
    def replace_citation(match):
        cite_group = match.group(1)
        chunk_ids = [int(x.strip()) for x in cite_group.split(',')]
        
        # Group by source type
        doc_chunks = []
        transcript_chunks = []
        
        for chunk_id in chunk_ids:
            metadata = chunks_metadata.get(chunk_id)
            if metadata:
                source_type = metadata.get("source_type", "document")
                if source_type == "meeting_transcript":
                    transcript_chunks.append(metadata)
                else:
                    doc_chunks.append(metadata)
        
        # Format citations
        citations = []
        
        # Format document citations
        if doc_chunks:
            doc_name = doc_chunks[0].get("document", "").replace(".pdf", "")
            pages = list(set(m.get("page") for m in doc_chunks if m.get("page")))
            pages_str = ", ".join([f"p.{p}" for p in sorted(pages) if p != "N/A"])
            if doc_name and pages_str:
                citations.append(f"{doc_name}({pages_str})")
        
        # Format transcript citations
        for transcript_meta in transcript_chunks:
            meeting_name = transcript_meta.get("meeting_name", "Meeting")
            start_time = transcript_meta.get("start_time", "")
            if meeting_name:
                time_suffix = f"@{start_time}" if start_time else ""
                citations.append(f"{meeting_name}{time_suffix}")
        
        if citations:
            return f"[{', '.join(citations)}]"
        
        return match.group(0)
    
    citation_pattern = r'\[CITE:([0-9,\s]+)\]'
    formatted_answer = re.sub(citation_pattern, replace_citation, answer_text)
    return formatted_answer


def extract_citations_metadata(answer_text: str, chunks_metadata: Dict) -> List[Dict]:
    """
    Extract citations and map to metadata for both documents and transcripts.
    
    Args:
        answer_text: The generated answer with [CITE:X] markers
        chunks_metadata: Dictionary mapping chunk IDs to metadata
        
    Returns:
        List of citation dictionaries with source-specific metadata
    """
    citation_pattern = r'\[CITE:([0-9,\s]+)\]'
    cited_chunks = re.findall(citation_pattern, answer_text)
    
    citations = []
    unique_chunks = set()
    
    for cite_group in cited_chunks:
        chunk_ids = [int(x.strip()) for x in cite_group.split(',')]
        unique_chunks.update(chunk_ids)
    
    for chunk_id in sorted(unique_chunks):
        metadata = chunks_metadata.get(chunk_id)
        if metadata:
            source_type = metadata.get("source_type", "document")
            
            if source_type == "meeting_transcript":
                # Transcript citation
                citations.append({
                    "chunk_id": str(chunk_id),
                    "source_type": "transcript",
                    "meeting_name": metadata.get("meeting_name"),
                    "meeting_date": metadata.get("meeting_date"),
                    "start_time": metadata.get("start_time"),
                    "end_time": metadata.get("end_time"),
                    "speakers": metadata.get("speakers", [])
                })
            else:
                # Document citation
                citations.append({
                    "chunk_id": str(chunk_id),
                    "source_type": "document",
                    "document_name": metadata.get("document"),
                    "page_number": metadata.get("page"),
                    "positions": metadata.get("positions", [])
                })
    
    return citations


def generate_answer(chunks: List, question: str) -> Dict:
    """
    Generate answer with citations supporting both documents and transcripts.
    Uses the exact system prompt from unified_query_pipeline.ipynb.
    
    Args:
        chunks: List of retrieved chunks (mix of documents and transcripts)
        question: The user query
        
    Returns:
        Dictionary with answer, raw_answer, chunks_metadata, and citations
    """
    try:
        logger.info(f"📝 generate_answer called with {len(chunks)} chunks")
        
        # Initialize LLM
        logger.info("🤖 Initializing ChatGroq LLM...")
        try:
            llm = ChatGroq(
                model_name="meta-llama/llama-4-scout-17b-16e-instruct",
                temperature=0,
                max_tokens=4096
            )
            logger.info("✅ ChatGroq LLM initialized")
        except Exception as llm_e:
            logger.error(f"❌ LLM initialization failed: {llm_e}")
            logger.error(traceback.format_exc())
            raise
        
        context_parts = []
        all_images = []
        chunks_metadata = {}
        
        for i, chunk in enumerate(chunks):
            chunk_id = i + 1
            source_type = chunk.metadata.get("source_type", "document")
            
            # Build chunk header
            if source_type == "meeting_transcript":
                meeting_name = chunk.metadata.get("meeting_name", "Meeting")
                meeting_date = chunk.metadata.get("meeting_date", "")
                start_time = chunk.metadata.get("start_time", "")
                speakers_json = chunk.metadata.get("speakers_in_chunk", "[]")
                speakers = json.loads(speakers_json) if isinstance(speakers_json, str) else speakers_json
                
                doc_header = f"### [CHUNK {chunk_id}] - TRANSCRIPT ###\n"
                doc_header += f"Meeting: {meeting_name}\n"
                doc_header += f"Date: {meeting_date}\n"
                doc_header += f"Time: {start_time}\n"
                doc_header += f"Speakers: {', '.join(speakers)}\n\n"
                
                # Store metadata for citation
                chunks_metadata[chunk_id] = {
                    "source_type": "meeting_transcript",
                    "meeting_name": meeting_name,
                    "meeting_date": meeting_date,
                    "start_time": start_time,
                    "end_time": chunk.metadata.get("end_time", ""),
                    "speakers": speakers
                }
                
                # Get transcript content
                doc_body = chunk.page_content
                
            else:
                # Document chunk
                doc_header = f"### [CHUNK {chunk_id}] - DOCUMENT ###\n"
                doc_body = ""
                
                positions_str = chunk.metadata.get("positions", "[]")
                positions = json.loads(positions_str) if isinstance(positions_str, str) else positions_str
                
                # Store metadata for citation
                chunks_metadata[chunk_id] = {
                    "source_type": "document",
                    "page": chunk.metadata.get("page_number", "N/A"),
                    "document": chunk.metadata.get("document_name", "document.pdf"),
                    "positions": positions
                }
                
                # Extract content
                if "original_content" in chunk.metadata:
                    orig_data = json.loads(chunk.metadata["original_content"])
                    text = orig_data.get("raw_text", "")
                    tables = orig_data.get("tables_html", [])
                    
                    doc_body += f"TEXT CONTENT:\n{text}\n"
                    if tables:
                        doc_body += "\nTABULAR DATA:\n" + "\n".join(tables) + "\n"
                    
                    all_images.extend(orig_data.get("images_base64", []))
                else:
                    doc_body += chunk.page_content
            
            context_parts.append(doc_header + doc_body)

        final_context = "\n\n".join(context_parts)
        
        # Use the exact system prompt from the notebook
        instruction_prompt = f"""You are a precise research assistant. Answer the user query using ONLY the provided context.

The context includes both DOCUMENT chunks (from PDFs) and TRANSCRIPT chunks (from meeting recordings).

CITATION RULES:
1. Add [CITE:X] citations ONLY after complete sentences or paragraphs
2. NEVER add citations inside tables, lists, or mid-sentence
3. For tables: Add a single citation AFTER the entire table
4. Example: "The results are shown below.\n\n[table here]\n\n[CITE:3]"
5. For information from multiple chunks, use [CITE:X, Y, Z] format
6. You can cite both documents and transcripts - they are equally valid sources
7. If information is not in the context, say "I don't have information about that"

USER QUERY: {question}

RESEARCH CONTEXT:
{final_context}

ANSWER (with [CITE:X] citations AFTER The end of the answer to summarize transcriptions:"""

        message_content = [{"type": "text", "text": instruction_prompt}]
        
        # Add images from document chunks (transcripts don't have images)
        logger.info(f"🖼️  Adding {min(len(all_images), 5)} images to context")
        for img_b64 in all_images[:5]:
            message_content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}
            })
        
        logger.info(f"📤 Invoking LLM with {len(message_content)} content parts...")
        logger.info(f"   Context length: {len(final_context)} chars")
        logger.info(f"   Question: {question[:100]}...")
        
        try:
            response = llm.invoke([HumanMessage(content=message_content)])
            logger.info(f"✅ LLM response received ({len(response.content)} chars)")
        except Exception as invoke_e:
            logger.error(f"❌ LLM invoke failed: {invoke_e}")
            logger.error(traceback.format_exc())
            raise
        
        # Format answer with citations
        logger.info("🔄 Formatting answer with citations...")
        formatted_answer = format_answer_with_citations(response.content, chunks_metadata)
        
        # Extract citation metadata
        logger.info("📋 Extracting citation metadata...")
        citations = extract_citations_metadata(response.content, chunks_metadata)
        logger.info(f"✅ Extracted {len(citations)} citations")
        
        return {
            "answer": formatted_answer,
            "raw_answer": response.content,
            "chunks_metadata": chunks_metadata,
            "citations": citations
        }
        
    except Exception as e:
        logger.error(f"❌ generate_answer failed: {e}")
        logger.error(f"   Error type: {type(e).__name__}")
        logger.error(f"   Full traceback:\n{traceback.format_exc()}")
        return {
            "answer": f"Error generating response: {str(e)}",
            "raw_answer": "",
            "chunks_metadata": {},
            "citations": []
        }


def quick_query(
    question: str,
    project_id: int,
    filter_type: str = "unified",
    top_k: int = 5
) -> Dict:
    """
    Complete RAG pipeline: Query, retrieve, and generate answer.
    
    Args:
        question: User's question
        project_id: Project ID for collection
        filter_type: "unified", "document", or "transcript"
        top_k: Number of chunks to retrieve
        
    Returns:
        Dictionary with answer and sources
    """
    logger.info("=" * 80)
    logger.info("🚀 UNIFIED QUERY PIPELINE")
    logger.info("=" * 80)
    logger.info(f"🔍 Query: {question}")
    logger.info(f"📊 Filter: {filter_type}")
    logger.info(f"📦 Top K: {top_k}")
    logger.info(f"🆔 Project ID: {project_id}")
    
    try:
        # Step 1: Retrieve chunks
        logger.info("\n📥 STEP 1: Retrieving chunks from ChromaDB...")
        retrieved_chunks = query_with_filter(
            question=question,
            project_id=project_id,
            top_k=top_k,
            filter_type=filter_type
        )
        
        if not retrieved_chunks:
            logger.warning("⚠️ No chunks retrieved from ChromaDB")
            return {
                "answer": "No relevant information found in the database.",
                "sources": []
            }
        
        logger.info(f"✅ Retrieved {len(retrieved_chunks)} chunks")
        logger.info(f"   Chunk sources: {[c.metadata.get('source_type', 'unknown') for c in retrieved_chunks]}")
        
        # Step 2: Generate answer
        logger.info("\n🤖 STEP 2: Generating answer with Llama 4 Scout...")
        try:
            result = generate_answer(retrieved_chunks, question)
            logger.info("✅ Answer generated successfully")
            logger.info(f"   Answer length: {len(result.get('raw_answer', ''))} chars")
            logger.info(f"   Citations count: {len(result.get('citations', []))}")
        except Exception as gen_e:
            logger.error(f"❌ Answer generation failed: {gen_e}")
            logger.error(traceback.format_exc())
            raise
        
        logger.info("=" * 80)
        
        return {
            "answer": result["raw_answer"],
            "sources": result["citations"],
            "chunks_metadata": result["chunks_metadata"]
        }
        
    except Exception as e:
        logger.error(f"\n❌ quick_query FAILED: {e}")
        logger.error(f"   Error type: {type(e).__name__}")
        logger.error(f"   Full traceback:\n{traceback.format_exc()}")
        raise  # Re-raise to propagate to endpoint


def get_standalone_question(question: str, history: List[Dict[str, str]]) -> str:
    """
    Given conversation history and a follow-up question, 
    rephrase the question to be standalone using the Rewriter prompt.
    
    Args:
        question: The current user question
        history: List of dicts with 'role' and 'content' keys
        
    Returns:
        The rephrased standalone question
    """
    try:
        llm = ChatGroq(
            model_name="meta-llama/llama-4-scout-17b-16e-instruct",
            temperature=0,
            max_tokens=256
        )
        
        # Build conversation history for context
        messages = [
            SystemMessage(content="Given the conversation history and a follow-up question, rephrase the follow-up to be a standalone question. Do not answer it, just rephrase it.")
        ]
        
        # Add history
        for msg in history:
            if msg["role"] == "user":
                messages.append(HumanMessage(content=msg["content"]))
            elif msg["role"] == "assistant":
                messages.append(AIMessage(content=msg["content"]))
        
        # Add the current question
        messages.append(HumanMessage(content=f"Rephrase this follow-up question to be standalone: {question}"))
        
        response = llm.invoke(messages)
        return response.content.strip()
        
    except Exception as e:
        print(f"❌ Rewriter error: {e}")
        # Fallback to original question if rewriting fails
        return question


async def streaming_chat(
    question: str,
    history: List[Dict[str, str]],
    chunks: List,
    chunks_metadata: Dict
) -> AsyncGenerator[str, None]:
    """
    Stream the answer generation with citations using llm.astream().
    Yields text chunks as they are generated, then yields a final JSON event
    with citation metadata.
    
    Args:
        question: Original user question
        history: Conversation history (list of dicts with 'role' and 'content')
        chunks: Retrieved chunks from ChromaDB
        chunks_metadata: Metadata mapping for citations
        
    Yields:
        Text chunks during streaming, then a final JSON metadata event
    """
    try:
        llm = ChatGroq(
            model_name="meta-llama/llama-4-scout-17b-16e-instruct",
            temperature=0,
            max_tokens=4096
        )
        
        # Build context from chunks (same as generate_answer)
        context_parts = []
        all_images = []
        
        for i, chunk in enumerate(chunks):
            chunk_id = i + 1
            source_type = chunk.metadata.get("source_type", "document")
            
            if source_type == "meeting_transcript":
                meeting_name = chunk.metadata.get("meeting_name", "Meeting")
                meeting_date = chunk.metadata.get("meeting_date", "")
                start_time = chunk.metadata.get("start_time", "")
                speakers_json = chunk.metadata.get("speakers_in_chunk", "[]")
                speakers = json.loads(speakers_json) if isinstance(speakers_json, str) else speakers_json
                
                doc_header = f"### [CHUNK {chunk_id}] - TRANSCRIPT ###\n"
                doc_header += f"Meeting: {meeting_name}\n"
                doc_header += f"Date: {meeting_date}\n"
                doc_header += f"Time: {start_time}\n"
                doc_header += f"Speakers: {', '.join(speakers)}\n\n"
                doc_body = chunk.page_content
                
            else:
                doc_header = f"### [CHUNK {chunk_id}] - DOCUMENT ###\n"
                doc_body = ""
                
                if "original_content" in chunk.metadata:
                    orig_data = json.loads(chunk.metadata["original_content"])
                    text = orig_data.get("raw_text", "")
                    tables = orig_data.get("tables_html", [])
                    
                    doc_body += f"TEXT CONTENT:\n{text}\n"
                    if tables:
                        doc_body += "\nTABULAR DATA:\n" + "\n".join(tables) + "\n"
                    
                    all_images.extend(orig_data.get("images_base64", []))
                else:
                    doc_body += chunk.page_content
            
            context_parts.append(doc_header + doc_body)

        final_context = "\n\n".join(context_parts)
        
        # Build the system prompt with conversation history
        history_str = ""
        if history:
            history_str = "\n\nCONVERSATION HISTORY:\n"
            for msg in history[-5:]:  # Last 5 messages for context
                role = msg["role"].upper()
                content = msg["content"]
                history_str += f"{role}: {content}\n"
        
        instruction_prompt = f"""You are a precise research assistant. Answer the user query using ONLY the provided context.

The context includes both DOCUMENT chunks (from PDFs) and TRANSCRIPT chunks (from meeting recordings).

CITATION RULES:
1. Add [CITE:X] citations ONLY after complete sentences or paragraphs
2. NEVER add citations inside tables, lists, or mid-sentence
3. For tables: Add a single citation AFTER the entire table
4. Example: "The results are shown below.\n\n[table here]\n\n[CITE:3]"
5. For information from multiple chunks, use [CITE:X, Y, Z] format
6. You can cite both documents and transcripts - they are equally valid sources
7. If information is not in the context, say "I don't have information about that"
8. The [CITE:X] format should NEVER be ignored.
{history_str}
USER QUERY: {question}

RESEARCH CONTEXT:
{final_context}

ANSWER (with [CITE:X] citations AFTER The end of the answer to summarize transcriptions:"""

        message_content = [{"type": "text", "text": instruction_prompt}]
        
        # Add images (up to 5)
        for img_b64 in all_images[:5]:
            message_content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}
            })
        
        # Stream the response
        full_answer = ""
        async for chunk in llm.astream([HumanMessage(content=message_content)]):
            if hasattr(chunk, 'content') and chunk.content:
                full_answer += chunk.content
                # Yield text chunk for streaming
                yield f"data: {json.dumps({'type': 'text', 'content': chunk.content})}\n\n"
        
        # After streaming completes, extract citations and yield metadata
        citations = extract_citations_metadata(full_answer, chunks_metadata)
        
        # Yield final metadata event
        metadata_event = {
            "type": "metadata",
            "citations": citations,
            "chunks_metadata": {str(k): v for k, v in chunks_metadata.items()}
        }
        yield f"data: {json.dumps(metadata_event)}\n\n"
        
        # Yield done event
        yield "data: [DONE]\n\n"
        
    except Exception as e:
        print(f"❌ Streaming generation failed: {e}")
        error_event = {
            "type": "error",
            "message": str(e)
        }
        yield f"data: {json.dumps(error_event)}\n\n"
