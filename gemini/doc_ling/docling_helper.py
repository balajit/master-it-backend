from typing import Optional
from docling.document_converter import DocumentConverter
from docling_core.types.doc import DocItemLabel, DoclingDocument, TableItem


def get_header_by_hierarchy(table: TableItem, doc: DoclingDocument) -> Optional[str]:
    """Traverse up the structural parent tree (via cref) until a section header is found."""
    current = table
    while current and hasattr(current, "parent") and current.parent:
        # Resolve parent pointer (e.g. "#/texts/12")
        parent_ref = current.parent.cref
        parent_item = doc.get_item(parent_ref) if hasattr(doc, "get_item") else None

        # Fallback dictionary resolution if get_item isn't supported on current version
        if not parent_item and parent_ref.startswith("#/"):
            parts = parent_ref.lstrip("#/").split("/")
            if len(parts) == 2 and hasattr(doc, parts[0]):
                collection = getattr(doc, parts[0])
                idx = int(parts[1])
                if 0 <= idx < len(collection):
                    parent_item = collection[idx]

        if parent_item and getattr(parent_item, "label", None) in [
            DocItemLabel.SECTION_HEADER,
            DocItemLabel.TITLE,
            DocItemLabel.SUBTITLE
        ]:
            return parent_item.text.strip()

        current = parent_item
    return None


def get_nearest_header_spatial(table: TableItem, doc: DoclingDocument) -> Optional[str]:
    """Finds the nearest section header located above the table on the exact same page."""
    if not table.prov:
        return None

    table_page = table.prov[0].page_no
    table_top = table.prov[0].bbox.t

    candidate_headers = []

    for text_item in doc.texts:
        if text_item.label in [DocItemLabel.SECTION_HEADER, DocItemLabel.TITLE, DocItemLabel.SUBTITLE]:
            for prov in text_item.prov:
                # Must be on the same page and above the top edge of the table
                if prov.page_no == table_page and prov.bbox.b <= table_top:
                    # Vertical distance between bottom of header and top of table
                    vertical_gap = table_top - prov.bbox.b
                    candidate_headers.append((vertical_gap, text_item.text.strip()))

    if candidate_headers:
        # Sort by smallest vertical gap
        candidate_headers.sort(key=lambda x: x[0])
        return candidate_headers[0][1]

    return None


def extract_tables_with_headers(file_path: str):
    converter = DocumentConverter()
    result = converter.convert(file_path)
    doc = result.document

    extracted_data = []

    for idx, table in enumerate(doc.tables):
        # 1. Try structural hierarchy first
        section_header = get_header_by_hierarchy(table, doc)

        # 2. Fall back to spatial proximity if hierarchy wasn't captured
        if not section_header:
            section_header = get_nearest_header_spatial(table, doc)

        if not section_header:
            section_header = "Unassigned / Document Root"

        # Export table data to pandas DataFrame or HTML/CSV
        df = table.export_to_dataframe()

        extracted_data.append({
            "table_index": idx + 1,
            "section_header": section_header,
            "page_no": table.prov[0].page_no if table.prov else "Unknown",
            "dataframe": df
        })

    return extracted_data


# --- Example Usage ---
if __name__ == "__main__":
    results = extract_tables_with_headers("sample_report.pdf")

    for item in results:
        print(f"=== Table #{item['table_index']} (Page {item['page_no']}) ===")
        print(f"📌 Associated Header: {item['section_header']}")
        print("Data Preview:")
        print(item["dataframe"].head(3))
        print("\n" + "=" * 50 + "\n")