from docling.document_converter import DocumentConverter
from docling_core.types.doc import DocItemLabel

converter = DocumentConverter()
result = converter.convert("sample.pdf")
doc = result.document

# Map items by their JSON reference string for fast lookup
item_map = {f"#/{item.self_ref}": item for item in doc.texts}

for item in doc.texts:
    # Filter for headings (e.g., SECTION_HEADER, TITLE)
    if item.label in [DocItemLabel.SECTION_HEADER, DocItemLabel.TITLE]:
        print(f"📌 Section: {item.text}")

        # Iterate over directly attached children
        for child_ref in item.children:
            child_item = item_map.get(child_ref.cref)
            if child_item:
                print(f"   └── [{child_item.label.value}] {child_item.text[:80]}...")
        print("-" * 50)