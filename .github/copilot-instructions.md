# GitHub Copilot Instructions for FastAPI RAG Project
Dont create unnesecary readme files , dont create .sh testing files , dont try to test endpoints yourself , tell me what to checck i will do it so in the swagger ui.


## Project Overview
Multi-tenant FastAPI RAG backend. 
- **Tenancy**: Each project has a unique ChromaDB collection.
- **Hardware**: GPU-heavy partitioning happens on a local laptop; API and vector storage are cloud-ready.
- **Storage**: Hybrid model (Local FS for dev, S3 for production).

## Development Rules
1. **Incremental Structure**: Do not create the entire project at once. Only build files requested in the current prompt.
2. **GPU Constraints**: Heavy partitioning (Unstructured `hi_res`) is restricted to the local worker script, NOT the FastAPI server.
3. **Change Log**: After every response, list:
   - **Files Created/Modified**: List paths.
   - **What Changed**: Brief functional summary.
4. **No Side Effects**: Do not create `.md` change logs in the codebase.
5. **Simplicity**: Use standard FastAPI dependencies and Pydantic models. Avoid complex wrappers.

## Core Technical Requirements
- **Auth**: JWT tokens with User/Project association.
- **RBAC**: 
  - Owner: Upload (Local/S3), Delete, Manage Members.
  - Member: Query/Chat only.
- **Messaging**: Use Redis (local) to mimic AWS SQS for notifying the Laptop Worker of new uploads.
- **ChromaDB**: Isolated collections per `project_id`. Unified search for docs and transcripts.

## RAG pipeline
for the rag pipeline you will be given 3 files 8_multi_modal_rag,transcript_ingestion,unified_query_pipeline , which HAS ALL THE LOGIC OF THE PIPELINE DO NOT DEVIATE FROM THIS LOGIC EVERYTHING IS TESTED IN THE PIPELINES. USE THE SAME CODE FOR FASTAPI BACKEND