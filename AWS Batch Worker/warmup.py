import os
import logging
from unstructured.partition.pdf import partition_pdf

# Set up simple logging to see progress during build
logging.basicConfig(level=logging.INFO)

def warmup():
    test_file = "test_complex.pdf"
    
    if not os.path.exists(test_file):
        print(f"❌ {test_file} not found! Caching skipped.")
        return

    print(f"🔥 Warming up with {test_file} to cache all AI models...")
    try:
        # This triggers Layout, Tables, and OCR models
        partition_pdf(
            filename=test_file,
            strategy="hi_res",
            infer_table_structure=True,
            extract_image_block_types=["Image"]
        )
        print("✅ All models cached successfully into /root/.cache")
    except Exception as e:
        print(f"⚠️ Warmup encountered an issue (but models might be cached): {e}")

if __name__ == "__main__":
    warmup()